"""조회(GET) API 전수 점검. 주문 생성·정정·취소(POST/DELETE)는 실계좌라 호출하지 않는다. 실행: python probe.py"""
import gzip, json, pathlib, sys, time, urllib.error, urllib.parse, urllib.request

sys.stdout.reconfigure(encoding="utf-8")
env = {k: v.strip() for k, v in (l.split("=", 1) for l in pathlib.Path(__file__).with_name(".env").read_text("utf-8-sig").splitlines()
       if "=" in l and not l.startswith("#"))}
BASE = "https://openapi.tossinvest.com"

def call(path, data=None, headers={}):
    req = urllib.request.Request(BASE + path, data=data, headers={"Accept-Encoding": "identity", **headers})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        b = e.read()
        b = gzip.decompress(b) if b[:2] == bytes([31, 139]) else b
        try:
            return e.code, json.loads(b)
        except ValueError:
            return e.code, b.decode(errors="replace")[:200]

_, t = call("/oauth2/token", urllib.parse.urlencode({"grant_type": "client_credentials",
    "client_id": env["TOSS_CLIENT_ID"], "client_secret": env["TOSS_CLIENT_SECRET"]}).encode(),
    {"Content-Type": "application/x-www-form-urlencoded"})
H = {"Authorization": f"Bearer {t['access_token']}"}
SEC = call("/api/v1/sectors", headers=H)[1]["result"]["sectors"][0]
SID = SEC.get("sectorId") or SEC.get("id")
HA = {**H, "X-Tossinvest-Account": env["TOSS_ACCOUNT_SEQ"]}

def shape(res):
    """데이터 내용은 찍지 않고 모양(키·건수)만."""
    r = res.get("result", res) if isinstance(res, dict) else res
    if isinstance(r, list):
        return f"{len(r)}건" + (f" 키={list(r[0])[:6]}" if r and isinstance(r[0], dict) else "")
    if isinstance(r, dict):
        return f"키={list(r)[:8]}"
    return str(r)[:80]

CASES = [  # (분류, 이름, 경로, 계좌헤더)
    ("시세", "현재가 US", "/api/v1/prices?symbols=AAPL,TSLA", 0),
    ("시세", "현재가 KR", "/api/v1/prices?symbols=005930", 0),
    ("시세", "호가 US", "/api/v1/orderbook?symbol=AAPL", 0),
    ("시세", "체결 US", "/api/v1/trades?symbol=AAPL", 0),
    ("시세", "상하한가 US", "/api/v1/price-limits?symbol=AAPL", 0),
    ("시세", "일봉 US", "/api/v1/candles?symbol=AAPL&interval=1d", 0),
    ("시세", "1분봉 US", "/api/v1/candles?symbol=AAPL&interval=1m", 0),
    ("종목", "종목정보 US+KR", "/api/v1/stocks?symbols=AAPL,005930", 0),
    ("종목", "전종목 NASDAQ", "/api/v1/stocks/all?market=NASDAQ", 0),
    ("종목", "매수유의 US", "/api/v1/stocks/AAPL/warnings", 0),
    ("종목", "투자자동향 KR", "/api/v1/stocks/005930/investor-trading", 0),
    ("종목", "투자자동향 US", "/api/v1/stocks/AAPL/investor-trading", 0),
    ("종목", "프로그램매매 KR", "/api/v1/stocks/005930/program-trades", 0),
    ("종목", "공매도 KR", "/api/v1/stocks/005930/short-selling", 0),
    ("종목", "신용거래 KR", "/api/v1/stocks/005930/credit-trades", 0),
    ("종목", "대차거래 KR", "/api/v1/stocks/005930/securities-lending", 0),
    ("시장", "환율", "/api/v1/exchange-rate?baseCurrency=USD&quoteCurrency=KRW", 0),
    ("시장", "장시간 KR", "/api/v1/market-calendar/KR", 0),
    ("시장", "장시간 US", "/api/v1/market-calendar/US", 0),
    ("시장", "랭킹 US 거래대금", "/api/v1/rankings?type=MARKET_TRADING_AMOUNT&marketCountry=US&duration=1d", 0),
    ("시장", "랭킹 US 상승률", "/api/v1/rankings?type=TOP_GAINERS&marketCountry=US&duration=1d", 0),
    ("시장", "랭킹 US 토스체결", "/api/v1/rankings?type=TOSS_SECURITIES_TRADING_AMOUNT&marketCountry=US&duration=1d", 0),
    ("지수", "지수 현재가", "/api/v1/market-indicators/prices?symbols=KOSPI,KOSDAQ", 0),
    ("지수", "지수 일봉", "/api/v1/market-indicators/KOSPI/candles?interval=1d", 0),
    ("지수", "지수 투자자", "/api/v1/market-indicators/KOSPI/investor-trading?interval=1d", 0),
    ("섹터", "섹터 목록", "/api/v1/sectors", 0),
    ("섹터", "섹터 랭킹 US", "/api/v1/sectors/rankings?type=TOP_GAINERS&marketCountry=US&duration=1d", 0),
    ("섹터", "섹터 상세 US", f"/api/v1/sectors/{SID}?marketCountry=US", 0),
    ("섹터", "섹터 종목 US", f"/api/v1/sectors/{SID}/stocks?marketCountry=US", 0),
    ("섹터", "섹터 ETF US", f"/api/v1/sectors/{SID}/etfs?marketCountry=US", 0),
    ("계좌", "계좌 목록", "/api/v1/accounts", 0),
    ("계좌", "보유주식", "/api/v1/holdings", 1),
    ("주문조회", "대기 주문", "/api/v1/orders?status=OPEN", 1),
    ("주문조회", "종료 주문", "/api/v1/orders?status=CLOSED", 1),
    ("주문조회", "조건주문 진행", "/api/v1/conditional-orders?status=OPEN", 1),
    ("주문조회", "조건주문 종료", "/api/v1/conditional-orders?status=CLOSED", 1),
    ("주문정보", "매수가능 USD", "/api/v1/buying-power?currency=USD", 1),
    ("주문정보", "매수가능 KRW", "/api/v1/buying-power?currency=KRW", 1),
    ("주문정보", "매도가능 AAPL", "/api/v1/sellable-quantity?symbol=AAPL", 1),
    ("주문정보", "수수료", "/api/v1/commissions", 1),
]

ok = 0
for cat, name, path, acct in CASES:
    time.sleep(1.1)  # ponytail: 그룹별 한도 무시하고 일괄 1.1초, 가장 빡빡한 ACCOUNT(1회/초) 기준
    code, res = call(path, headers=HA if acct else H)
    good = code == 200
    ok += good
    detail = shape(res) if good else (res.get("error", res) if isinstance(res, dict) else res)
    if good and not isinstance(res, dict):
        detail = shape(res)
    print(f"{'O' if good else 'X'} [{cat}] {name}: {code} {detail if good else json.dumps(detail, ensure_ascii=False)[:160]}")
print(f"\n{ok}/{len(CASES)} 성공")
