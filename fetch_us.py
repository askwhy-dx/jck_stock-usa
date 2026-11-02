"""미국 보통주 유니버스 + 일봉 캐시 (토스 Open API).

유니버스 = NYSE·NASDAQ·AMEX 보통주(securityType=STOCK) 중 스팩 제외 · 시총(발행주식수 x 현재가) >= 1,000억 원.
일봉 = data/candles/{SYM}.json  [[YYYY-MM-DD, o, h, l, c, v], ...] 오름차순 · 확정봉만(미국 장 마감 전 오늘 봉 제외).
캐시가 있으면 최신 200봉만 받아 이어 붙이고, 없으면 2021-01-01 이전까지 거슬러 받는다.

사용: python fetch_us.py   (첫 실행 약 20~30분, 이후 약 3분)
"""
import datetime as dt, json, zoneinfo
from concurrent.futures import ThreadPoolExecutor

from toss import HERE, get

DATA = HERE / "data"
CANDLES = DATA / "candles"
CANDLES.mkdir(parents=True, exist_ok=True)
MIN_CAP_KRW = 1000e8
FROM = "2021-01-01"  # 2022~ 사례 + MA224 예열
ET = zoneinfo.ZoneInfo("America/New_York")


def last_confirmed():
    """확정봉 마지막 날짜(미국 동부 기준). 16:30 ET 전이면 어제까지."""
    now = dt.datetime.now(ET)
    return (now.date() if now.hour * 60 + now.minute >= 16 * 60 + 30 else now.date() - dt.timedelta(days=1)).isoformat()


def universe():
    syms = []
    for m in ("NYSE", "NASDAQ", "AMEX"):
        syms += [x["symbol"] for x in get("/api/v1/stocks/all", tps=1, market=m, securityType="STOCK", commonShare="true")]
    rate = float(get("/api/v1/exchange-rate", tps=3, baseCurrency="USD", quoteCurrency="KRW")["rate"])
    out = {}
    for i in range(0, len(syms), 200):
        chunk = ",".join(syms[i:i + 200])
        info = {x["symbol"]: x for x in get("/api/v1/stocks", symbols=chunk)}
        price = {x["symbol"]: float(x["lastPrice"]) for x in get("/api/v1/prices", tps=15, symbols=chunk) if x.get("lastPrice")}
        for s, x in info.items():
            eng = (x.get("englishName") or "").upper()
            sh = float(x.get("sharesOutstanding") or 0)
            if "ACQUISITION" in eng or x.get("status") != "ACTIVE" or s not in price:
                continue
            cap_krw = sh * price[s] * rate
            if cap_krw >= MIN_CAP_KRW:
                out[s] = dict(name=x["name"], eng=x.get("englishName"), market=x["market"], shares=sh,
                              cap_krw_billion=round(cap_krw / 1e8), list_date=x.get("listDate"))
    (DATA / "universe.json").write_text(json.dumps(dict(date=dt.date.today().isoformat(), usdkrw=rate, stocks=out),
                                                  ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"유니버스 {len(out)}종 (보통주 {len(syms)} 중 · USD/KRW {rate})")
    return out


def candles(sym, last):
    p = CANDLES / f"{sym}.json"
    old = json.loads(p.read_text()) if p.exists() else []
    bars, before = {}, None
    while True:
        r = get("/api/v1/candles", tps=20, symbol=sym, interval="1d", count=200, before=before)
        for c in r["candles"]:
            d = c["timestamp"][:10]
            if d <= last:
                bars[d] = [d, *(float(c[k]) for k in ("openPrice", "highPrice", "lowPrice", "closePrice", "volume"))]
        oldest = r["candles"][-1]["timestamp"][:10] if r["candles"] else FROM
        before = r.get("nextBefore")
        if not before or oldest < FROM or (old and oldest <= old[-1][0]):
            break
    merged = {b[0]: b for b in old} | bars
    rows = sorted(merged.values())
    p.write_text(json.dumps(rows, separators=(",", ":")))
    return len(rows)


def main():
    uni = universe()
    last = last_confirmed()
    def safe(s):
        try:
            return candles(s, last)
        except Exception as e:
            print(f"  [실패] {s}: {e}")
            return 0

    done = 0
    with ThreadPoolExecutor(8) as ex:
        for sym, n in zip(uni, ex.map(safe, uni)):
            done += 1
            if done % 250 == 0:
                print(f"  일봉 {done}/{len(uni)}")
    print(f"일봉 캐시 완료 {done}종 · 확정봉 마지막 {last}")


if __name__ == "__main__":
    main()
