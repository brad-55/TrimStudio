"""E2E: tailnet (Tailscale) access control. Skips when no tailnet address is present."""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import security  # noqa: E402

BASE = "http://127.0.0.1:8003"
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else "  " + str(detail)))
    if not cond:
        fails += 1


def status(url, host=None):
    req = urllib.request.Request(url, headers={"Host": host} if host else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:120]
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def main():
    names, ips = security.tailnet_info(0)
    v4 = [ip for ip in ips if ":" not in ip and security.is_tailnet_ip(ip)]
    if not v4:
        local = [ip for ip in security.local_interface_ips() if security.is_tailnet_ip(ip)]
        v4 = local
    if not v4:
        print("SKIP tailnet e2e: no tailnet address on this machine")
        return 0
    tn_ip = v4[0]
    print("tailnet address:", tn_ip, "names:", sorted(names))

    st, _ = status(BASE + "/api/health")
    check("loopback still allowed", st == 200, st)

    st, _ = status("http://%s:8003/api/health" % tn_ip)
    check("tailnet address + own host allowed", st == 200, st)

    st, _ = status("http://%s:8003/api/health" % tn_ip, host="evil.example.com")
    check("foreign host rejected over tailnet", st == 403, st)

    if names:
        name = sorted(names)[0]
        st, _ = status("http://%s:8003/api/health" % tn_ip, host=name)
        check("magicDNS name allowed", st == 200, st)

    st, _ = status("http://%s:8003/api/health" % tn_ip, host="other.tailnet.ts.net")
    check("other ts.net name allowed (tailnet trust)", st == 200, st)

    st, _ = status("http://%s:8003/" % tn_ip)
    check("UI loads over tailnet", st == 200, st)

    print("RESULT:", "OK" if fails == 0 else "FAIL(%d)" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
