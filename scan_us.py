"""미국판 🎯 손익비 돌파 + 🍚 밥그릇3 — stock/ 국내 스캐너 정의를 그대로 옮긴 것.

🎯 손익비 = stock/screen_rr_breakout.py 와 같은 신호·통과·과거 유사 사례 기대값 (상수·산식 동일).
🍚 밥그릇3 = stock/screen_bowl3_quality.py --no-pullback 모드:
    대상 = 돌파 풀(stock/collect_breakout_flow.py) active + 지속관찰 — 풀 상태 파일 대신
           2026-06-10(국내 풀 시작일)부터 일봉으로 생애주기를 다시 계산한다
           (종목당 첫 포착만 · 매일 고점 +10% → 졸업 / 돌파선 종가 이탈 → 이탈 · 둘 다 아니면 남음)
    + 3개년 매출·순이익 strict 연속 증가 + 올해 악재 공시 0건 (DART → SEC, sec.py)
국내와 다른 점: 시총 = 현재 발행주식수 x 그날 종가 x 오늘 환율 · 상장폐지 종목은 과거 사례에 없음 · 눌림 풀 없음.

사용: python scan_us.py   (먼저 python fetch_us.py)
"""
import datetime as dt, json, sys

import numpy as np

import sec
from toss import HERE

DATA = HERE / "data"
TP, H, LB, TOPN, MIN_N = 0.10, 60, 15, 5, 30
EB, EU, EV, EC = [.5, .8], [.05, .15], [3, 10], [.06, .10, .20]
POOL_START = "2026-06-10"
MIN_CAP = 1e11  # 1,000억 원


def ma(x, n):
    c = np.cumsum(np.insert(x, 0, 0))
    m = np.full(len(x), np.nan)
    m[n - 1:] = (c[n:] - c[:-n]) / n
    return m


def bins(b, u, vr, ch):
    return (int(np.digitize(b, EB)), int(np.digitize(u, EU)), int(np.digitize(vr, EV)), int(np.digitize(ch, EC)))


def score_breakout(ret, vr, line, yang):
    """collect_breakout_flow.score_breakout (유형1, 추종 없음)."""
    s = 35 if ret >= .17 else 28 if ret >= .13 else 20
    s += 35 if vr >= 7 else 27 if vr >= 5 else 20 if vr >= 4 else 12
    s += 20 if line == "112+224" else 15 if line == "224" else 10
    return min(100, s + (6 if yang else 0))


_dn = lambda p: np.floor(round(p * 100, 6)) / 100  # 미국 호가 $0.01
_up = lambda p: np.ceil(round(p * 100, 6)) / 100


def plan(a):
    """stock/auto_intake.js scenario() 이식 — 1·2·3차(1:1:2) · 손절 · 목표. a = 전일까지 확정봉 [o,h,l,c,v]."""
    h, l, c = a[:, 1], a[:, 2], a[:, 3]
    C = c[-1]
    m = {n: c[-n:].mean() for n in (20, 60, 112, 224)}
    named = [m[n] for n in (112, 224) if m[n] <= C]
    w = l[-120:]
    lows = [(w[i], "저점") for i in range(5, len(w) - 1) if w[i] == w[i - 5:i + 6].min()]
    cands = ([(max(named), "MA112·224")] if named else []) + sorted(
        [x for x in [(m[n], f"MA{n}") for n in (20, 60, 112, 224)] + lows if x[0] <= C * 0.995], key=lambda x: -x[0])
    for S, basis in cands:
        stop = _dn(S * .99); p3 = _up(stop / .98); p1 = _dn(min(C, S * 1.04))
        if p1 - p3 < .02:
            continue
        p2 = max(_dn(p1 - (p1 - p3) * .4), _up(p1 * .98))
        p2 = round(p1 - .01, 2) if p2 >= p1 else p2
        p2 = round(p3 + .01, 2) if p2 <= p3 else p2
        if p2 < p1:
            break
    else:
        return dict(ok=False, reason="지지선 위 1·2·3차 간격 부족" if cands else "종가 아래 지지선 없음")
    avg = (p1 + p2 + 2 * p3) / 4
    w = h[-240:]
    res = sorted({w[i] for i in range(5, len(w) - 1) if w[i] == w[i - 5:i + 6].max()} | {h[-20:].max()})
    res = [x for x in res if x > avg * 1.05]
    target = next((x for x in res if avg * 1.08 <= x <= avg * 1.15), None)
    in_gate = target is not None
    target = target if in_gate else res[0] if res else None
    if target is None:
        return dict(ok=False, reason="평단 위 저항대 없음 (목표 산출 불가)")
    rr = (target - avg) / (avg - stop)
    hold = "목표 ≤ 현재가 (1차까지 눌림 대기)" if target <= C else f"손익비 {rr:.2f} < 1.5" if rr < 1.5 else ""
    return dict(ok=True, basis=basis, p1=p1, p2=p2, p3=p3, stop=stop, avg=round(avg, 2), target=round(target, 2),
                in_gate=in_gate, rr=round(rr, 2), stop_pct=round((1 - stop / avg) * 100, 1),
                target_pct=round((target / avg - 1) * 100, 1), hold=hold)


def plan_txt(p):
    q = p["plan"]
    if not q["ok"]:
        return f"\n      분할: 산출 불가 — {q['reason']}"
    return (f"\n      분할 1차 ${q['p1']} · 2차 ${q['p2']} · 3차 ${q['p3']} (1:1:2, 평단 ${q['avg']}) "
            f"· 손절 ${q['stop']}(-{q['stop_pct']}%) · 목표 ${q['target']}(+{q['target_pct']}%{'' if q['in_gate'] else ', 8~15% 밖'}) "
            f"· 손익비 {q['rr']}" + (f" · ⚠️ 보류: {q['hold']}" if q["hold"] else ""))


def load():
    uni = json.loads((DATA / "universe.json").read_text(encoding="utf-8"))
    out = {}
    for s, meta in uni["stocks"].items():
        p = DATA / "candles" / f"{s}.json"
        if p.exists():
            rows = json.loads(p.read_text())
            if len(rows) >= 300:
                out[s] = (meta, [r[0] for r in rows], np.array([r[1:] for r in rows], dtype=float))
    return uni["usdkrw"], out


def main():
    today = dt.date.today().isoformat()
    rate, stocks = load()
    last = max(d[-1] for _, d, _ in stocks.values())
    hist, cand, pool = [], [], []
    np.seterr(divide="ignore", invalid="ignore")
    for sym, (meta, dates, a) in stocks.items():
        if dates[-1] != last:
            continue
        o, h, l, c, v = a.T
        cap = c * meta["shares"] * rate
        m112, m224 = ma(c, 112), ma(c, 224)
        L = np.fmax(m112, m224)
        v20 = ma(v, 20)
        n = len(c)
        # ---- 🎯 손익비 (screen_rr_breakout.main 과 같은 루프) ----
        for i in range(225, n):
            if cap[i] < MIN_CAP or not (c[i - 1] <= L[i - 1] and c[i] > L[i]) or c[i] <= o[i] or h[i] <= l[i]:
                continue
            rg = h[i] - l[i]
            f = ((c[i] - o[i]) / rg, (h[i] - c[i]) / rg, v[i] / v20[i - 1], c[i] / c[i - 1] - 1)
            if not f[2] >= 2:
                continue
            if i < n - H:
                for k in range(i, min(i + LB, n - H)):
                    sw = 1 - L[k] * 0.99 / c[k]
                    if 0.02 <= sw <= 0.05 and c[k] > o[k] and c[k] > L[k]:
                        break
                else:
                    continue
                S, T, res, win = L[k] * 0.99, c[k] * (1 + TP), c[k + H] / c[k] - 1, 0
                for j in range(k + 1, k + 1 + H):
                    if h[j] >= T:
                        res, win = TP, 1
                        break
                    if c[j] <= S:
                        res = c[j] / c[k] - 1
                        break
                hist.append(bins(*f) + (win, res))
            elif i >= n - LB:
                sw = 1 - L[-1] * 0.99 / c[-1]
                if c[-1] > L[-1] and 0.02 <= sw <= 0.05 and c[-1] > o[-1] and f[0] >= 0.5:
                    cand.append(dict(sym=sym, signal_date=dates[i], f=f, close=c[-1], line=L[-1], stop_pct=sw))
        # ---- 🍚 돌파 풀 재계산 (collect_breakout_flow.scan_breakouts + update_pool) ----
        va = ma(v, 20)  # 국내와 같이 당일 포함 20일 평균
        for i in range(max(225, next((k for k, d in enumerate(dates) if d >= POOL_START), n)), n):
            x112, x224 = c[i - 1] <= m112[i - 1] and c[i] > m112[i], c[i - 1] <= m224[i - 1] and c[i] > m224[i]
            ret, vr = c[i] / c[i - 1] - 1, v[i] / va[i] if va[i] > 0 else 0
            if not (x112 or x224) or not (ret >= .10 and vr >= 3 and c[i] / max(m112[i], m224[i]) - 1 <= .30):
                continue
            line = "112+224" if x112 and x224 else "112" if x112 else "224"
            sc = score_breakout(ret, vr, line, c[i] > o[i])
            if cap[i] < MIN_CAP or sc < 80:
                continue
            status, peak = ("active" if i == n - 1 else "지속관찰"), 0.0
            for j in range(i + 1, n):
                peak = max(peak, c[j] / c[i] - 1)
                if peak >= .10:
                    status = "졸업"
                    break
                if (line != "224" and c[j] < m112[j]) or (line != "112" and c[j] < m224[j]):
                    status = "이탈"
                    break
            pool.append(dict(sym=sym, name=meta["name"], eng=meta["eng"], market=meta["market"], status=status,
                             breakout_date=dates[i], line=line, ret_pct=round(ret * 100, 1), vmult=round(vr, 1),
                             score=sc, close=round(c[-1], 2), peak_pct=round(peak * 100, 1)))
            break  # 종목당 첫 포착만 (국내 풀은 이미 있는 종목을 다시 넣지 않음)

    Hh = np.array(hist, dtype=float)
    best = {}
    for x in cand:
        m = (Hh[:, :4] == np.array(bins(*x["f"]))).all(1)
        cnt = int(m.sum())
        if cnt < MIN_N or Hh[m, 5].mean() <= 0:
            continue
        b, u, vr, ch = x["f"]
        meta = stocks[x["sym"]][0]
        row = dict(sym=x["sym"], name=meta["name"], eng=meta["eng"], market=meta["market"], signal_date=x["signal_date"],
                   close=round(x["close"], 2), line=round(x["line"], 2), stop=round(x["line"] * 0.99, 2),
                   stop_pct=round(x["stop_pct"] * 100, 2), rr=round(TP / x["stop_pct"], 2), body=round(b, 3),
                   vmult=round(vr, 2), chg_pct=round(ch * 100, 2), n=cnt, win=round(float(Hh[m, 4].mean()), 3),
                   ev_pct=round(float(Hh[m, 5].mean()) * 100, 2))
        if x["sym"] not in best or row["signal_date"] > best[x["sym"]]["signal_date"]:
            best[x["sym"]] = row

    cmap = sec.cik_map()
    rr = []
    for r in sorted(best.values(), key=lambda r: -r["ev_pct"]):
        if len(rr) >= TOPN:
            break
        r |= sec.screen(r["sym"], cmap, today)
        if r["negative"]:
            print(f"[rr]  제외 {r['sym']} — 올해 {r['disclosure']}")
            continue
        rr.append(r)

    b3_uni = sorted([p for p in pool if p["status"] in ("active", "지속관찰")], key=lambda p: -p["score"])
    b3_pass, b3_rej = [], []
    for p in b3_uni:
        p |= sec.screen(p["sym"], cmap, today)
        ok = p["fin_ok"] and not p["negative"]
        p["reason"] = "3년 성장 + 공시 청정" if ok else p["fin"] if not p["fin_ok"] else p["disclosure"]
        (b3_pass if ok else b3_rej).append(p)
    for r in rr + b3_pass:
        r["plan"] = plan(stocks[r["sym"]][2])
        r["toss"] = f"https://tossinvest.com/stocks/{r['sym']}"

    out = dict(date=today, us_date=last, usdkrw=rate, universe=len(stocks), hist_events=len(Hh),
               baseline=dict(win=round(float(Hh[:, 4].mean()), 3), ev_pct=round(float(Hh[:, 5].mean()) * 100, 2)),
               rr=dict(candidates=len(cand), similar_ok=len(best), picks=rr),
               bowl3=dict(pool=dict((s, sum(p["status"] == s for p in pool)) for s in ("active", "지속관찰", "졸업", "이탈")),
                          passed=b3_pass, top=b3_pass[:TOPN], rejected=b3_rej))
    if "--dry-run" not in sys.argv:
        (DATA / f"us_scan_{today}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    print(f"\n미국 {last} 확정봉 · 유니버스 {len(stocks)}종 · 과거 사례 {len(Hh)}건 "
          f"(전체 승률 {out['baseline']['win']:.0%} · 기대값 {out['baseline']['ev_pct']:+.2f}%)")
    print(f"\n🎯 손익비 — 후보 {len(cand)} → 유사사례 통과 {len(best)} → 선정 {len(rr)}")
    for i, r in enumerate(rr, 1):
        print(f"  {i}. {r['sym']} {r['name']} 신호 {r['signal_date']} 종가 ${r['close']} 손절 ${r['stop']}(-{r['stop_pct']}%) "
              f"손익비 {r['rr']} · n={r['n']} 승 {r['win']:.0%} 기대 {r['ev_pct']:+.2f}% · 공시 {r['disclosure']} · 재무 {r['fin']}"
              + (f" · {r['badges'][0]}" if r["badges"] else "") + plan_txt(r))
    print(f"\n🍚 밥그릇3 — 돌파 풀 {out['bowl3']['pool']} → 대상 {len(b3_uni)} → 통과 {len(b3_pass)}")
    for i, p in enumerate(b3_pass[:TOPN], 1):
        print(f"  {i}. {p['sym']} {p['name']} {p['score']}점 · {p['status']} · 돌파 {p['breakout_date']}({p['line']}, +{p['ret_pct']}%, {p['vmult']}배) "
              f"· 종가 ${p['close']} · 매출 {p['sales']} · 순익 {p['net_inc']}" + (f" · {p['badges'][0]}" if p["badges"] else "") + plan_txt(p))
    for p in b3_rej:
        print(f"  ✗ {p['sym']} {p['name']} {p['score']}점 — {p['reason']}")


if __name__ == "__main__":
    main()
