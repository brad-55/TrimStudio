"""LAN dual-stack launcher for the Trim server (IPv4 + IPv6 on one socket)."""
import socket
import sys

import uvicorn

from . import security
from .config import Config
from .main import app


def lan_urls(port, scheme="http"):
    urls = []
    for ip in sorted(security.local_interface_ips()):
        if ip.startswith("127.") or ip == "::1":
            continue
        host = "[" + ip + "]" if ":" in ip else ip
        urls.append(scheme + "://" + host + ":" + str(port) + "/")
    return urls


def dual_stack_socket(port):
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except OSError:
            pass
        sock.bind(("::", port))
        sock.listen(2048)
        return sock
    except OSError:
        return None


def main():
    cfg = Config()
    host = cfg.get("host", "0.0.0.0")
    port = int(cfg.get("port", 8003))
    print("Trim starting on port " + str(port))
    for url in lan_urls(port):
        print("  LAN: " + url)
    print("  local: http://127.0.0.1:" + str(port) + "/")
    if cfg.get("strongMode"):
        print("  strongMode: enter this token in the UI -> " + security.load_or_create_token(cfg.data_dir))
    # Trim assumes a single process: the job semaphore, output-path reservation
    # and SSE state all live in memory. Do not run with multiple workers.
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    if host in ("0.0.0.0", "::"):
        sock = dual_stack_socket(port)
        if sock is not None:
            print("dual-stack socket bound to [::]:" + str(port))
            server.run(sockets=[sock])
            return 0
        print("dual-stack bind failed; falling back to IPv4 only")
    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
