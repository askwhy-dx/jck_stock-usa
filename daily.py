"""평일 22:00 — 수집 → 스캔 → 손절 고정 → 단테 대시보드 🇺🇸 USA 탭 → Slack(단테와 같은 채널) → 업로드.

손절 고정 = ../jck_stock/build_bowl3_tab.js 와 같은 규칙: 처음 들어온 날의 1·2·3차·손절·목표를 data/usa_state.json 에 저장해 유지,
최신 확정 종가 < 손절이면 탭에서 삭제 + Slack 🛑 + 20거래일 재진입 금지, 스캔에서 빠지거나 5자리 밖이면 조용히 정리.
표시 전용 — 국내 스윙 카드·stocks.json·§6 에는 넣지 않는다. 주문 API 는 부르지 않는다(실계좌).

사용: python daily.py [--dry-run] [--skip-run]
  --dry-run   상태·대시보드 저장, Slack, 업로드 생략 (Slack 문구와 탭 HTML 을 화면에 출력)
  --skip-run  수집·스캔 생략, 가장 최근 data/us_scan_*.json 사용
"""
import datetime as dt, html, json, re, subprocess, sys, traceback, urllib.request

from toss import HERE

DATA = HERE / "data"
STOCK = HERE.parent / "jck_stock"
DASH = STOCK / "분석_대시보드.html"
STATE = DATA / "usa_state.json"
DASH_URL = "https://jichang999-dotcom.github.io/tes2/financial/분석_대시보드.html"
TOPN, BAN_DAYS = 5, 20
DRY, SKIP = "--dry-run" in sys.argv, "--skip-run" in sys.argv
SEC_RE = re.compile(r'<section id="usa-tab-summary">[\s\S]*?</section>')
KIND = {"rr": "🎯 손익비", "b3": "🍚 밥그릇3"}


def env():
    out = {}
    for line in (HERE.parent / ".env").read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"')
    return out


def slack(text, blocks=None):
    if DRY:
        print(f"\n----- Slack (dry-run) -----\n{text}\n---------------------------")
        return
    e = env()
    body = dict(username=e.get("SLACK_USERNAME") or "단테 자동분석", icon_emoji=e.get("SLACK_ICON_EMOJI") or ":chart_with_upwards_trend:", text=text)
    for b in ([blocks] if blocks else []) + [None]:  # table 블록이 거부되면 글자만 다시 보냄 (slack_send.js 와 같은 대체)
        req = urllib.request.Request(e["SLACK_WEBHOOK_URL"], json.dumps(body | ({"blocks": b} if b else {})).encode(), {"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=30)
            return
        except urllib.error.HTTPError as err:
            print(f"Slack {err.code} — {'글자만 재발송' if b else '실패'}")


def run(step, args, cwd=HERE):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(r.stdout[-3000:])
    if r.returncode:
        raise RuntimeError(f"{step} 실패 (exit {r.returncode}) — {(r.stderr or r.stdout).strip().splitlines()[-1:] or ['출력 없음']}")


def closes(sym):
    p = DATA / "candles" / f"{sym}.json"
    return json.loads(p.read_text()) if p.exists() else []


def update_state(scan):
    """손절 고정·이탈 삭제·재진입 금지. 반환 = (종류별 표시 목록, 이탈 목록)."""
    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else dict(managed={}, banned={})
    picks = {"rr": scan["rr"]["picks"], "b3": scan["bowl3"]["passed"]}
    bars = {}
    since = lambda sym, d: sum(r[0] > d for r in bars.setdefault(sym, closes(sym)))
    exits = []
    for key, m in list(st["managed"].items()):
        rows = bars.setdefault(m["sym"], closes(m["sym"]))
        if rows and rows[-1][4] < m["stop"]:
            exits.append(f"• *{m['sym']}* {m['name']} ({KIND[m['kind']]}) — 종가 ${rows[-1][4]:.2f} < 손절 ${m['stop']} ({rows[-1][0][5:]} 종가)")
            st["banned"][key] = dict(name=m["name"], exit_us_date=rows[-1][0])
            del st["managed"][key]
        elif not any(p["sym"] == m["sym"] for p in picks[m["kind"]]):
            print(f"정리 {key} — 오늘 스캔에서 빠짐")
            del st["managed"][key]
        else:
            m["dplus"] = since(m["sym"], m["first_us_date"])
    for key, b in list(st["banned"].items()):
        if since(key.split(":")[1], b["exit_us_date"]) >= BAN_DAYS:
            del st["banned"][key]
    top = {}
    for kind, ps in picks.items():
        top[kind] = []
        for p in ps:
            key = f"{kind}:{p['sym']}"
            if len(top[kind]) >= TOPN:
                break
            if key in st["banned"]:
                continue
            if key not in st["managed"]:
                q = p.get("plan") or {}
                if not q.get("ok"):
                    print(f"건너뜀 {key} — {q.get('reason', '분할 계획 없음')}")
                    continue
                st["managed"][key] = dict(kind=kind, sym=p["sym"], name=p["name"], first_date=scan["date"], first_us_date=scan["us_date"],
                                          dplus=0, **{k: q[k] for k in ("p1", "p2", "p3", "stop", "target", "rr")})
            top[kind].append((p, st["managed"][key], bars.setdefault(p["sym"], closes(p["sym"]))[-1][4]))
        for key in [k for k, m in st["managed"].items() if m["kind"] == kind and not any(m["sym"] == p["sym"] for p, _, _ in top[kind])]:
            del st["managed"][key]  # 5자리 밖 — 다시 들어오면 새로 산출
    holiday = st.get("last_us_date") == scan["us_date"]
    st["last_us_date"] = scan["us_date"]
    if not DRY:
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return top, exits, holiday


def status(m, close):
    return "⏸ 눌림 대기 (목표 ≤ 현재가)" if close >= m["target"] else f"⚠️ 손익비 {m['rr']} &lt; 1.5" if m["rr"] < 1.5 else "✅"


def fin_cell(p):
    return (f"{'✅' if p['fin_ok'] else '➖'} {html.escape(p.get('fin') or '-')}<br>{'✅ 공시 ' + p['disclosure'] if not p['negative'] else '❌ ' + html.escape(p['disclosure'])}"
            + "".join(f"<br>⚠️ {html.escape(b)}" for b in p.get("badges") or []))


def render(scan, top):
    td = lambda l, v: f'<td data-label="{l}">{v}</td>'
    usd = lambda x: f"${x:,.2f}"

    def table(kind, extra_head, extra):
        head = ["순위", "종목", "경과", *extra_head, "현재가", "1차", "2차", "3차", "손절", "목표", "손절 폭", "손익비", "재무·공시", "상태"]
        rows = [f"      <tr>{td('순위', i)}{td('종목', f'<strong>{p['sym']}</strong> {html.escape(p['name'])} <span class=\"hd-note\">{p['market']}</span><br><a href=\"{p['toss']}\" target=\"_blank\">토스 ↗</a>')}"
                f"{td('경과', f'D+{m['dplus']}')}{''.join(td(h, v) for h, v in zip(extra_head, extra(p)))}{td('현재가', usd(c))}"
                + "".join(td(h, usd(m[k])) for h, k in (("1차", "p1"), ("2차", "p2"), ("3차", "p3"), ("손절", "stop"), ("목표", "target")))
                + f"{td('손절 폭', f'−{(1 - m['stop'] / m['p1']) * 100:.1f}%')}{td('손익비', f'{m['rr']:.2f}')}{td('재무·공시', fin_cell(p))}{td('상태', status(m, c))}</tr>"
                for i, (p, m, c) in enumerate(top[kind], 1)]
        body = "\n".join(rows) or f'      <tr><td colspan="{len(head)}">해당 없음</td></tr>'
        return (f'  <table class="stock-table" style="font-size:0.88em;">\n    <thead><tr>{"".join(f"<th>{h}</th>" for h in head)}</tr></thead>\n'
                f"    <tbody>\n{body}\n    </tbody>\n  </table>")

    rr, b3 = scan["rr"], scan["bowl3"]
    rej = {}
    for p in b3["rejected"]:
        rej.setdefault(p["reason"], []).append(p["sym"])
    now = dt.datetime.now().strftime("%m-%d %H:%M")
    return f"""<section id="usa-tab-summary">
  <h3 style="margin:8px 0;">🇺🇸 USA <span class="hd-note">(미국 {scan['us_date']} 확정 종가 · 갱신 {now} · 환율 {scan['usdkrw']:,.0f}원 · 유니버스 {scan['universe']:,}종 · 표시 전용, 자동 편입·주문 없음)</span></h3>
  <h4 style="margin:12px 0 4px;">🎯 손익비 <span class="hd-note">(후보 {rr['candidates']} → 유사사례 통과 {rr['similar_ok']} → 선정 {len(rr['picks'])} · 기대값 순 최대 5종)</span></h4>
{table('rr', ['신호일', '승률(n)', '기대값'], lambda p: [p['signal_date'][5:], f"{p['win']:.0%} ({p['n']})", f"{p['ev_pct']:+.2f}%"])}
  <h4 style="margin:12px 0 4px;">🍚 밥그릇3 <span class="hd-note">(🇺🇸 미국 정의 · 돌파 풀 {b3['pool']['지속관찰'] + b3['pool']['active']}종 → 통과 {len(b3['passed'])} · 점수 순 최대 5종)</span></h4>
{table('b3', ['점수', '돌파'], lambda p: [p['score'], f"{p['breakout_date'][5:]} {p['line']}<br>+{p['ret_pct']}% · {p['vmult']}배"])}
  <details style="margin-top:8px;"><summary class="hd-note">밥그릇3 탈락 {len(b3['rejected'])}종 (사유별)</summary>
  <p class="hd-note">{'<br>'.join(f"{html.escape(k)} — {', '.join(v)}" for k, v in rej.items()) or '없음'}</p></details>
  <div class="highlight" style="margin-top:12px;">
  <strong>🇺🇸 미국 정의 (국내와 다른 부분)</strong>
  <ul class="hd-note" style="margin:4px 0;">
    <li><strong>🍚 밥그릇3</strong> = 국내 10-21 이전 정의(돌파 풀). 2026-06-10 이후 112·224선 첫 돌파(+10%↑·거래량 3배↑·점수 80↑) 중 +10% 졸업도 돌파선 이탈도 안 한 종목 + 매출·순이익 3개 회계연도 연속 증가 + 올해 악재 공시 0건. 국내 현행(3구간 눌림 + 외국인·기관 수급)은 미국 수급 데이터가 없어 미적용</li>
    <li><strong>재무·공시</strong> = SEC EDGAR (국내 DART). 악재 = 공모·사모 발행·상장기준 미달·상장폐지·보고 지연·재무제표 신뢰불가·파산 + <strong>인수합병 진행</strong>(미국 전용 — 인수가에 묶인 종목이 돌파 풀을 점령해서 제외)</li>
    <li><strong>시총</strong> = 현재 발행주식수 × 그날 종가 × 오늘 환율 (근사) · 과거 유사 사례에 상장폐지 종목 없음 · 해외 기업(20-F)은 SEC 재무가 1년 늦을 수 있음</li>
  </ul>
  공통 = 손익비 신호·과거 유사 사례·분할매수(1:1:2) 산식은 국내와 같음 · 1·2·3차·손절·목표는 들어온 날 값으로 고정 · 매일 확정 종가 &lt; 손절이면 삭제(Slack 🛑) 후 20거래일 재진입 금지 · 경과 D+N = 들어온 뒤 미국 거래일
  </div>
</section>"""


def message(scan, top, holiday):
    d = dt.date.fromisoformat(scan["us_date"])
    title = f"🇺🇸 *단테 USA* — 미국 {d:%m-%d}({'월화수목금토일'[d.weekday()]}) 종가 기준" + ("\n⚠️ 새 확정봉 없음 (미국 휴장 추정 — 전날과 같은 결과)" if holiday else "")
    rows = [[f"{p['sym']} {p['name']}", f"${m['p1']:,.2f}", f"${m['stop']:,.2f}", "✅" if p["fin_ok"] else "➖"] for p, m, _ in top["rr"]]
    rr_lines = [f"• *{r[0]}* · 1차 {r[1]} · 손절 {r[2]} · 재무 {r[3]}" for r in rows] or ["해당 없음"]
    b3_lines = [f"{i}. *{p['sym']}* {p['name']} · 1차 ${m['p1']:,.2f} · 손절 ${m['stop']:,.2f}" + (" · ⏸ 눌림 대기" if c >= m["target"] else "")
                for i, (p, m, c) in enumerate(top["b3"], 1)] or ["해당 없음"]
    foot = f"밥그릇3 탈락 {len(scan['bowl3']['rejected'])}종 · <{DASH_URL}|📊 대시보드 USA 탭>"
    text = "\n".join([title, "", "*🎯 손익비*", *rr_lines, "", "*🍚 밥그릇3*", *b3_lines, "", foot])
    sec = lambda t: {"type": "section", "text": {"type": "mrkdwn", "text": t}}
    blocks = [sec(title), sec("*🎯 손익비*")]
    blocks += [{"type": "table", "column_settings": [{"align": "left"}, {"align": "center"}, {"align": "center"}, {"align": "center"}],
                "rows": [[{"type": "raw_text", "text": t} for t in r] for r in [["종목", "1차", "손절", "재무"], *rows]]}] if rows else [sec("해당 없음")]
    blocks += [sec("*🍚 밥그릇3*\n" + "\n".join(b3_lines)), {"type": "context", "elements": [{"type": "mrkdwn", "text": foot}]}]
    return text, blocks


def main():
    step = "수집"
    try:
        if not SKIP:
            run("① 수집 fetch_us.py", [sys.executable, "-u", "fetch_us.py"])
            step = "스캔"
            run("② 스캔 scan_us.py", [sys.executable, "-u", "scan_us.py"])
        step = "탭·알림"
        scan = json.loads(max(DATA.glob("us_scan_*.json")).read_text(encoding="utf-8"))
        top, exits, holiday = update_state(scan)
        sec_html = render(scan, top)
        if DRY:
            print(sec_html)
        else:
            page = DASH.read_text(encoding="utf-8")
            if not SEC_RE.search(page):
                raise RuntimeError("대시보드에 #usa-tab-summary 마커 없음")
            DASH.write_text(SEC_RE.sub(lambda _: sec_html, page, count=1), encoding="utf-8")
        if exits:
            slack(f"🛑 *손절 이탈 — USA에서 삭제* ({len(exits)}종)\n" + "\n".join(exits))
        slack(*message(scan, top, holiday))
        if not DRY:
            step = "업로드"
            run("③ 업로드 upload_dashboard.js", ["node", "upload_dashboard.js"], cwd=STOCK)
        for f in (DATA / "sec").glob("*"):  # SEC 하루 캐시 — 7일 지난 것 삭제
            if f.is_file() and dt.datetime.now().timestamp() - f.stat().st_mtime > 7 * 86400 and not DRY:
                f.unlink()
    except Exception as e:
        traceback.print_exc()
        slack(f"⚠️ *단테 USA 실행 실패* — {step} 단계\n```{str(e)[:500]}```")
        sys.exit(1)


if __name__ == "__main__":
    main()
