"""LAN confinement, CSRF token, and path safety helpers."""
import ipaddress
import os
import secrets
import socket
from pathlib import Path


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


def local_interface_ips():
    ips = {"127.0.0.1", "::1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ips.add(info[4][0])
    except OSError:
        pass
    return ips


def host_allowed(host_header, cfg_ips, self_names=None):
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
    if name.lower() == "localhost":
        return True
    ip = normalize_ip(name)
    if ip is None:
        # Only accept names enumerated on this host. Resolving an attacker supplied name
        # would let DNS rebinding impersonate this server and bypass same-origin checks.
        return bool(self_names) and name.lower() in self_names
    return bool(ip.is_loopback or str(ip) in cfg_ips)


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
