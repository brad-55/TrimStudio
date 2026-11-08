"""LAN / tailnet confinement, CSRF token, and path safety helpers."""
import ipaddress
import json
import os
import secrets
import shutil
import socket
import subprocess
import time
from pathlib import Path

# Tailscale hands out addresses from the CGNAT shared range (100.64.0.0/10);
# IPv6 tailnet addresses live in the ULA range and are already covered by is_private_ip.
TAILNET_NETWORKS = (ipaddress.ip_network("100.64.0.0/10"),)
WINDOWS_TAILSCALE = r"C:\Program Files\Tailscale	ailscale.exe"
_tailnet_cache = {"at": 0.0, "names": frozenset(), "ips": frozenset()}


def normalize_ip(raw):
    if not raw:
        return None
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip


def is_private_ip(raw):
    ip = normalize_ip(raw)
    if ip is None:
        return False
    return bool(ip.is_loopback or ip.is_private or ip.is_link_local)


def is_tailnet_ip(raw):
    """True for a Tailscale tailnet IPv4 address (100.64.0.0/10, CGNAT shared space)."""
    ip = normalize_ip(raw)
    if ip is None or isinstance(ip, ipaddress.IPv6Address):
        return False
    return any(ip in net for net in TAILNET_NETWORKS)


def is_allowed_source(raw, allow_tailnet=True):
    """Loopback / RFC1918 / link-local, plus the tailnet range when enabled."""
    return bool(is_private_ip(raw) or (allow_tailnet and is_tailnet_ip(raw)))


def tailnet_info(ttl=300.0):
    """This machine's own Tailscale name(s) and address(es), cached.

    Uses the Tailscale CLI when it is available; returns empty sets otherwise.
    Best effort only: a failure must never break requests.
    """
    now = time.time()
    if now - _tailnet_cache["at"] < ttl:
        return _tailnet_cache["names"], _tailnet_cache["ips"]
    names, ips = set(), set()
    exe = None
    if os.name == "nt" and os.path.exists(WINDOWS_TAILSCALE):
        exe = WINDOWS_TAILSCALE
    else:
        exe = shutil.which("tailscale")
    if exe:
        try:
            proc = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=5)
            data = json.loads(proc.stdout or "{}")
            me = data.get("Self") or {}
            dns = (me.get("DNSName") or "").rstrip(".")
            if dns:
                names.add(dns.lower())
            for item in me.get("TailscaleIPs") or []:
                norm = normalize_ip(item)
                if norm is not None:
                    ips.add(str(norm))
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    _tailnet_cache.update({"at": now, "names": frozenset(names), "ips": frozenset(ips)})
    return _tailnet_cache["names"], _tailnet_cache["ips"]


def local_interface_ips():
    ips = {"127.0.0.1", "::1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ips.add(info[4][0])
    except OSError:
        pass
    return ips


def host_allowed(host_header, cfg_ips, self_names=None, allow_tailnet=True,
                 tailnet_names=None, tailnet_ips=None, client_is_tailnet=False):
    if not host_header:
        return False
    host = host_header.strip()
    if host.startswith("["):
        end = host.find("]")
        name = host[1:end] if end > 0 else host
    else:
        name = host.split(":")[0]
    if not name:
        return False
    lower = name.lower().rstrip(".")
    if lower == "localhost":
        return True
    ip = normalize_ip(name)
    if ip is None:
        # Names are only accepted when they are known to belong to this machine
        # (enumerated names, or the Tailscale name reported by the local CLI).
        # Resolving an attacker supplied name would let DNS rebinding impersonate
        # this server and bypass same-origin checks.
        if tailnet_names and lower in tailnet_names:
            return True
        if allow_tailnet and len(lower) > len(".ts.net") and lower.endswith(".ts.net"):
            # Tailscale MagicDNS name. ts.net is controlled by Tailscale, so a rebinding
            # attacker cannot register a name there; the source address check above still
            # limits requests to the LAN/tailnet.
            return True
        return bool(self_names) and lower in self_names
    if ip.is_loopback or str(ip) in cfg_ips:
        return True
    if allow_tailnet and tailnet_ips and str(ip) in tailnet_ips:
        return True
    return False


def self_host_names():
    names = {"localhost", "localhost.localdomain"}
    try:
        host = socket.gethostname().lower()
        names.add(host)
        fqdn = socket.getfqdn().lower()
        if fqdn:
            names.add(fqdn)
        names.add(host + ".local")
        names.add(host.split(".")[0])
    except OSError:
        pass
    return names


def is_within(child, parent):
    try:
        child_real = os.path.realpath(str(child))
        parent_real = os.path.realpath(str(parent))
    except OSError:
        return False
    if child_real == parent_real:
        return True
    try:
        return os.path.commonpath([child_real, parent_real]) == parent_real
    except ValueError:
        return False


def check_path(raw_path, cfg):
    if not raw_path:
        raise ValueError("empty path")
    p = Path(raw_path)
    if not p.is_absolute():
        raise ValueError("path must be absolute")
    real = os.path.realpath(str(p))
    if not any(is_within(real, root) for root in cfg.allowed_roots):
        raise PermissionError("path outside allowed roots: " + str(real))
    if any(is_within(real, deny) for deny in cfg.deny_roots):
        raise PermissionError("path is denied: " + str(real))
    return real


def load_or_create_token(data_dir):
    token_path = Path(data_dir) / "csrf.token"
    if token_path.exists():
        token = token_path.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    token_path.write_text(token, encoding="utf-8")
    return token
