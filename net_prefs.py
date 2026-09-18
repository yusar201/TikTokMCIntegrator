"""Network address-family preferences for hosts with a broken IPv6 path.

Why this exists: some ISP routes deliver IPv4 fine but silently black-hole
IPv6. A host that advertises an AAAA record then looks reachable while every
connection to it hangs until timeout, and the failure is invisible — the name
resolves, so nothing reports "IPv6 is dead".

Measured on the reporting operator's line (2026-09-17), TCP connects to the
TikTok sign server:

    IPv6 2606:4700:20::681a:1ab   0/10 succeeded
    IPv4 104.26.0.171             1/5      (and 7/10 in an earlier sample)
    IPv4 webcast.tiktok.com      10/10, 2ms
    IPv4 1.1.1.1                 10/10, 2ms

TikTokLive signs its websocket through that sign host on every connect *and*
every reconnect, and Python resolves the AAAA record first — so the bot burned
attempt after attempt on an address family that could never work, surfacing as
`SignAPIError ... Failed to connect to the sign server due to an
httpx.ConnectError` / `httpcore.ConnectError: All connection attempts failed`.

Scope: this only filters ordinary (AF_UNSPEC) lookups in the bot process. An
explicit AF_INET6 lookup is still honoured, and a host that has no IPv4 address
keeps its IPv6 answers, so nothing becomes unreachable.
"""
from __future__ import annotations

import socket

_original_getaddrinfo = None


def _ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
    original = _original_getaddrinfo
    if original is None:
        raise RuntimeError("IPv4 resolver wrapper installed without an original")
    results = original(host, port, family, type, proto, flags)
    if family == socket.AF_INET6:
        return results
    ipv4 = [entry for entry in results if entry[0] == socket.AF_INET]
    # Fall back to whatever was returned when there is no IPv4 answer at all —
    # an IPv6-only host must still resolve.
    return ipv4 or results


def is_forced() -> bool:
    """True when the IPv4-only wrapper is currently installed."""
    return getattr(socket.getaddrinfo, "_ipv4_only_wrapper", False)


def force_ipv4(enabled: bool = True):
    """Install (or remove) the IPv4-only resolver wrapper. Idempotent.

    Returns the resolver that was in place before the call, or None.
    """
    global _original_getaddrinfo

    if enabled:
        if is_forced():
            return _original_getaddrinfo
        _original_getaddrinfo = socket.getaddrinfo
        _ipv4_only._ipv4_only_wrapper = True           # type: ignore[attr-defined]
        socket.getaddrinfo = _ipv4_only
        return _original_getaddrinfo

    if is_forced() and _original_getaddrinfo is not None:
        socket.getaddrinfo = _original_getaddrinfo
        _original_getaddrinfo = None
    return None


def apply_setting(settings) -> bool:
    """Apply `Settings.ForceIPv4` from a loaded config. Defaults to ON.

    Defaulting ON is deliberate: IPv4 works on every link, so preferring it
    costs nothing real, while a silently dead IPv6 path costs every connect.
    Set `ForceIPv4: false` to restore normal dual-stack behaviour.
    """
    enabled = True
    if isinstance(settings, dict) and "ForceIPv4" in settings:
        enabled = bool(settings.get("ForceIPv4"))
    force_ipv4(enabled)
    return enabled
