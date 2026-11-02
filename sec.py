"""SEC EDGAR — DART 대신 쓰는 미국 재무·공시 판정 (stock/screen_bowl3_quality.py 의 조건 2·3 대응).

재무 = 최근 3개 회계연도(10-K·20-F·40-F 연간) 매출·순이익이 모두 있고 strict 연속 증가인지.
공시 = 올해(1/1~) 제출 공시 중 악재 0건인지. DART 악재 패턴 → SEC 대응:
    유증·CB·BW  → S-1 · F-1 · 424B4(공모) · 8-K 3.02(사모 발행)
    관리·상폐    → 8-K 3.01(상장 유지 기준 미달·상폐 통지) · Form 25 · NT 10-K/10-Q/20-F(정기보고 지연)
    감사부적정    → 8-K 4.02(과거 재무제표 신뢰 불가)
    파산         → 8-K 1.03
    인수합병 진행 → PREM14A·DEFM14A·SC 14D9·SC TO-T·SC 13E3, 또는 같은 날 8-K 1.01 + DEFA14A
                   (국내 DART 패턴에 없는 미국 전용 추가 · 26-10-20 — 인수가에 묶여 돌파 풀 「지속관찰」에 영구히 남던 종목 5/7)
    424B5(일괄신고 발행)는 주식인지 채권인지 문서를 열어야 알 수 있어 제외하지 않고 배지로만 남긴다.
"""
import datetime as dt, json, time, urllib.request

from toss import HERE, env

UA = env.get("SEC_USER_AGENT") or "stock-usa research contact@stock-usa.dev"
CACHE = HERE / "data" / "sec"
CACHE.mkdir(parents=True, exist_ok=True)
REV = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
       "RevenueFromContractWithCustomerIncludingAssessedTax", "Revenue"]
NET = ["NetIncomeLoss", "ProfitLoss", "ProfitLossAttributableToOwnersOfParent"]
ANNUAL = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
BAD_FORMS = {"S-1": "공모(S-1)", "F-1": "공모(F-1)", "424B4": "공모(424B4)", "25": "상장폐지(25)", "25-NSE": "상장폐지(25)",
             "NT 10-K": "보고 지연", "NT 10-Q": "보고 지연", "NT 20-F": "보고 지연"}
BAD_ITEMS = {"3.02": "사모 발행(8-K 3.02)", "3.01": "상장기준 미달(8-K 3.01)", "4.02": "재무제표 신뢰불가(8-K 4.02)",
             "1.03": "파산(8-K 1.03)"}
MERGER = {"PREM14A", "DEFM14A", "PREM14C", "DEFM14C", "SC 14D9", "SC TO-T", "SC 13E3"}
_last = 0.0


def _get(url, cache_name):
    """하루 1회 캐시. SEC 한도 초당 10회 → 0.12초 간격."""
    global _last
    p = CACHE / cache_name
    if p.exists() and dt.date.fromtimestamp(p.stat().st_mtime) == dt.date.today():
        return json.loads(p.read_text(encoding="utf-8"))
    time.sleep(max(0, _last + 0.12 - time.time()))
    _last = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            d = {}
        else:
            raise
    p.write_text(json.dumps(d), encoding="utf-8")
    return d


def cik_map():
    d = _get("https://www.sec.gov/files/company_tickers.json", "company_tickers.json")
    return {v["ticker"].upper(): f"{v['cik_str']:010d}" for v in d.values()}


def _annual(facts, tags):
    """태그 중 가장 최근 회계연도까지 있는 것 하나로 [전전, 전, 당] (끝나는 날 기준)."""
    best = None
    for ns in ("us-gaap", "ifrs-full"):
        for t in tags:
            for unit, rows in ((facts.get(ns) or {}).get(t, {}).get("units") or {}).items():
                by_end = {}
                for x in rows:
                    if x.get("form") not in ANNUAL or not x.get("start"):
                        continue
                    days = (dt.date.fromisoformat(x["end"]) - dt.date.fromisoformat(x["start"])).days
                    if 330 <= days <= 400 and (x["end"] not in by_end or x["filed"] > by_end[x["end"]][0]):
                        by_end[x["end"]] = (x["filed"], x["val"])
                if by_end and (best is None or max(by_end) > max(best)):
                    best = by_end
    if not best:
        return None, None
    ends = sorted(best)[-3:]
    if len(ends) < 3 or any(not 330 <= (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days <= 400
                            for a, b in zip(ends, ends[1:])):
        return None, ends[-1]
    return [best[e][1] for e in ends], ends[-1]


def screen(ticker, cmap, today):
    """→ dict(fin_ok, fin, sales, net_inc, fy_end, disclosure, negative, badges)"""
    cik = cmap.get(ticker.upper().replace(".", "-")) or cmap.get(ticker.upper())
    if not cik:
        return dict(fin_ok=None, fin="SEC 미등록", disclosure="미확인(SEC 미등록)", negative=[], badges=[])
    facts = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", f"facts_{cik}.json").get("facts") or {}
    sales, fy_end = _annual(facts, REV)
    net, _ = _annual(facts, NET)
    inc = lambda s: bool(s) and s[0] < s[1] < s[2]
    if sales is None or net is None:
        fin_ok, fin = None, "재무 없음"
    else:
        fin_ok = inc(sales) and inc(net)
        fin = "3년 성장" if fin_ok else " · ".join(n for n, s in (("매출", sales), ("순이익", net)) if not inc(s)) + " 증가 아님"
    r = (_get(f"https://data.sec.gov/submissions/CIK{cik}.json", f"sub_{cik}.json").get("filings") or {}).get("recent") or {}
    year0 = f"{today[:4]}-01-01"
    neg, badges, defa, deal = [], [], set(), set()
    for form, d, items in zip(r.get("form", []), r.get("filingDate", []), r.get("items", [])):
        if d < year0:
            continue
        hit = BAD_FORMS.get(form) or ("인수합병 진행" if form in MERGER else None)
        defa |= {d} if form == "DEFA14A" else set()
        deal |= {d} if form.startswith("8-K") and "1.01" in items.split(",") else set()
        if not hit and form.startswith("8-K"):
            hit = next((BAD_ITEMS[i] for i in items.split(",") if i in BAD_ITEMS), None)
        if hit:
            neg.append(dict(date=d, form=form, matched=hit))
        elif form == "424B5":
            badges.append(d)
    if defa & deal and not any(n["matched"] == "인수합병 진행" for n in neg):
        neg.append(dict(date=min(defa & deal), form="8-K 1.01 + DEFA14A", matched="인수합병 진행"))
    return dict(fin_ok=fin_ok, fin=fin, sales=sales, net_inc=net, fy_end=fy_end,
                disclosure="청정" if not neg else "악재: " + ", ".join(sorted({n["matched"] for n in neg})),
                negative=neg, badges=[f"424B5 발행 {len(badges)}건"] if badges else [])


if __name__ == "__main__":
    import sys
    cm = cik_map()
    for t in sys.argv[1:] or ["AAPL", "NVDA", "TSM"]:
        x = screen(t, cm, dt.date.today().isoformat())
        print(t, {k: v for k, v in x.items() if k != "negative"}, x["negative"][:3])
