"""키 연결 확인: 토큰 발급 -> 환율 -> 계좌 목록. 실행: python check.py"""
import gzip, json, pathlib, sys, urllib.parse, urllib.request

sys.stdout.reconfigure(encoding="utf-8")

env = dict(l.split("=", 1) for l in pathlib.Path(__file__).with_name(".env").read_text("utf-8-sig").splitlines()
           if "=" in l and not l.startswith("#"))
BASE = "https://openapi.tossinvest.com"

def call(path, data=None, headers={}):
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        b = e.read()
        raise SystemExit(f"{e.code} {path}: {(gzip.decompress(b) if b[:2] == bytes([31, 139]) else b).decode()}")

tok = call("/oauth2/token", urllib.parse.urlencode({
    "grant_type": "client_credentials",
    "client_id": env["TOSS_CLIENT_ID"].strip(),
    "client_secret": env["TOSS_CLIENT_SECRET"].strip(),
}).encode(), {"Content-Type": "application/x-www-form-urlencoded"})["access_token"]
auth = {"Authorization": f"Bearer {tok}"}
print("토큰 OK")
print("환율:", call("/api/v1/exchange-rate?baseCurrency=USD&quoteCurrency=KRW", headers=auth))
print("계좌:", call("/api/v1/accounts", headers=auth))
if seq := env.get("TOSS_ACCOUNT_SEQ", "").strip():
    h = call("/api/v1/holdings", headers={**auth, "X-Tossinvest-Account": seq})["result"]
    print("보유주식 조회 OK:", list(h) if isinstance(h, dict) else f"{len(h)}건")
