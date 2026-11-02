"""토스 Open API 최소 클라이언트. 토큰은 클라이언트당 1개만 유효하므로 프로세스당 한 번만 받는다."""
import gzip, json, pathlib, sys, threading, time, urllib.error, urllib.parse, urllib.request

sys.stdout.reconfigure(encoding="utf-8")
HERE = pathlib.Path(__file__).parent
env = {k: v.strip() for k, v in (l.split("=", 1) for l in (HERE / ".env").read_text("utf-8-sig").splitlines()
       if "=" in l and not l.startswith("#"))}
BASE = "https://openapi.tossinvest.com"
_tok, _lock, _last = None, threading.Lock(), {}


def _req(url, data=None, headers={}):
    req = urllib.request.Request(url, data=data, headers={"Accept-Encoding": "gzip", **headers})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            b, code, hd = r.read(), r.status, r.headers
    except urllib.error.HTTPError as e:
        b, code, hd = e.read(), e.code, e.headers
    b = gzip.decompress(b) if b[:2] == bytes([31, 139]) else b
    return code, b, hd


def token():
    global _tok
    if not _tok:
        code, b, _ = _req(BASE + "/oauth2/token", urllib.parse.urlencode({"grant_type": "client_credentials",
            "client_id": env["TOSS_CLIENT_ID"], "client_secret": env["TOSS_CLIENT_SECRET"]}).encode(),
            {"Content-Type": "application/x-www-form-urlencoded"})
        if code != 200:
            raise SystemExit(f"토큰 실패 {code}: {b[:200]}")
        _tok = json.loads(b)["access_token"]
    return _tok


def get(path, tps=5, **params):
    """GET → result. tps = 그 API 그룹 초당 한도(스레드 공유). 429 는 Retry-After 만큼 대기 후 재시도."""
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    for attempt in range(6):
        with _lock:  # ponytail: 그룹 구분 없이 tps 별 간격만 맞춤, 그룹 섞어 병렬 돌리면 더 촘촘히
            wait = _last.get(tps, 0) + 1 / tps - time.time()
            if wait > 0:
                time.sleep(wait)
            _last[tps] = time.time()
        code, b, hd = _req(f"{BASE}{path}?{q}", headers={"Authorization": f"Bearer {token()}"})
        if code == 200:
            return json.loads(b)["result"]
        if code == 429 or code >= 500:
            time.sleep(float(hd.get("Retry-After") or 2 ** attempt))
            continue
        raise RuntimeError(f"{code} {path} {q}: {b[:200].decode(errors='replace')}")
    raise RuntimeError(f"재시도 초과 {path} {q}")
