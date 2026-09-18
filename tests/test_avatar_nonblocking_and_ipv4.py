"""Avatar downloads must never block the bot's event loop, and IPv4 can be forced.

Two fixes for a link that loses packets:

  1. `cache_avatar_image` used to do a blocking `urlopen(timeout=8)` on the
     calling thread. Twelve async event handlers call it (follow, like, comment
     and nine SuperFan paths), so every uncached avatar that timed out froze the
     whole bot for 8 seconds — no events processed, no websocket keep-alive sent.
     A real session logged two such freezes in five minutes.

  2. When the local IPv6 path is dead but IPv4 works, a host that advertises an
     AAAA record makes Python try IPv6 first, so every connect (and reconnect)
     burns an attempt on an address family that can never succeed. Measured on
     the reporter's line: 0/10 IPv6 connects to the sign server vs 1/5 IPv4.
"""
import re
import socket
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


# ── 1. avatar downloads are off-thread ───────────────────────────────────────

@pytest.fixture
def av(monkeypatch, tmp_path):
    import avatar_cache as ac

    monkeypatch.setattr(ac, "AVATAR_ASSETS_DIR", str(tmp_path))
    return ac


def test_cache_avatar_image_returns_before_the_download_finishes(av, monkeypatch):
    calls = []

    def slow_download(url, nick="", unique_id=""):
        calls.append(url)
        time.sleep(0.4)          # would freeze the loop for 0.4s if inline
        return ""

    monkeypatch.setattr(av, "_download_avatar", slow_download)

    start = time.monotonic()
    result = av.cache_avatar_image("https://cdn.example/a.jpg", "nick", "uid")
    elapsed = time.monotonic() - start

    assert result == "", "an uncached avatar must fall back, not block"
    assert elapsed < 0.15, f"cache_avatar_image blocked for {elapsed:.2f}s"
    assert av.wait_for_downloads(5.0) is True
    assert calls == ["https://cdn.example/a.jpg"]


def test_repeat_sightings_schedule_only_one_download(av, monkeypatch):
    calls = []

    def slow_download(url, nick="", unique_id=""):
        calls.append(url)
        time.sleep(0.25)
        return ""

    monkeypatch.setattr(av, "_download_avatar", slow_download)

    for _ in range(5):
        av.cache_avatar_image("https://cdn.example/a.jpg", "nick", "uid")
    av.wait_for_downloads(5.0)

    assert len(calls) == 1, calls


def test_cached_avatar_returns_immediately_without_network(av, monkeypatch):
    stem = av._safe_key("nick", "uid", "https://cdn.example/a.jpg")
    (Path(av.AVATAR_ASSETS_DIR) / (stem + ".jpg")).write_bytes(b"\xff\xd8\xff" + b"x" * 32)

    def explode(*_args, **_kwargs):
        raise AssertionError("a cached avatar must not trigger a download")

    monkeypatch.setattr(av, "_download_avatar", explode)

    assert av.cache_avatar_image("https://cdn.example/a.jpg", "nick", "uid") == f"/avatar_cache/{stem}.jpg"


def test_failed_download_is_swallowed_and_unblocks_the_slot(av, monkeypatch, capsys):
    def failing_download(url, nick="", unique_id=""):
        raise OSError("network is unreachable")

    monkeypatch.setattr(av, "_download_avatar", failing_download)

    assert av.cache_avatar_image("https://cdn.example/a.jpg", "nick", "uid") == ""
    assert av.wait_for_downloads(5.0) is True
    assert av.pending_downloads() == 0
    # The in-flight slot must be released so a later sighting can retry.
    assert "AVATAR-CACHE" in capsys.readouterr().out


def test_local_and_data_urls_short_circuit(av):
    assert av.cache_avatar_image("/avatar_cache/x.jpg") == "/avatar_cache/x.jpg"
    assert av.cache_avatar_image("data:image/png;base64,AAA") == ""
    assert av.cache_avatar_image("") == ""


def test_resolve_avatar_path_performs_no_network_io():
    """The handler-facing avatar helpers must stay network-free.

    Asserting "every call site wraps this in to_thread" would be the wrong
    contract: twelve handlers reach this path (follow, like, comment and nine
    SuperFan flows) and one of them is a plain sync helper that cannot await.
    The guarantee lives in avatar_cache instead, so this checks the boundary the
    handlers actually cross.
    """
    source = (ROOT / "minecraft_main.py").read_text(encoding="utf-8")
    resolve_body = source[source.index("def resolve_avatar_url("):source.index("def update_gifter_ranking(")]
    cache_body = source[source.index("def _cache_avatar_url("):source.index("def _cached_avatar_url(")]

    assert "urlopen" not in resolve_body, "avatar resolution must not fetch on the loop"
    assert "_cache_avatar_url(" in resolve_body
    assert "urlopen" not in cache_body, "_cache_avatar_url must not fetch on the loop"
    assert "cache_avatar_image(" in cache_body, "downloads must go through the queued cache"


def test_blocking_download_is_not_reachable_on_the_loop():
    """cache_avatar_image must contain no direct network call of its own."""
    source = (ROOT / "avatar_cache.py").read_text(encoding="utf-8")
    body = source[source.index("def cache_avatar_image("):source.index("def _download_avatar(")]
    assert "urlopen" not in body, "cache_avatar_image must not perform network I/O"


# ── 2. forcing IPv4 ──────────────────────────────────────────────────────────

@pytest.fixture
def net_prefs():
    import net_prefs as np

    yield np
    np.force_ipv4(False)


def _fake_getaddrinfo(*hosts):
    entries = []
    for family, ip in hosts:
        entries.append((family, socket.SOCK_STREAM, 6, "", (ip, 443)))
    return lambda *a, **k: list(entries)


def test_force_ipv4_drops_ipv6_answers(net_prefs, monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        _fake_getaddrinfo((socket.AF_INET6, "2606:4700::1"), (socket.AF_INET, "104.26.0.171")),
    )
    net_prefs.force_ipv4(True)

    resolved = socket.getaddrinfo("tiktok-legacy.eulerstream.com", 443)

    assert [r[0] for r in resolved] == [socket.AF_INET]
    assert resolved[0][4][0] == "104.26.0.171"


def test_force_ipv4_keeps_ipv6_only_hosts_working(net_prefs, monkeypatch):
    """Never make an IPv6-only host unreachable."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo((socket.AF_INET6, "2606:4700::1")))
    net_prefs.force_ipv4(True)

    assert socket.getaddrinfo("v6only.example", 443)[0][0] == socket.AF_INET6


def test_force_ipv4_respects_an_explicit_ipv6_request(net_prefs, monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        _fake_getaddrinfo((socket.AF_INET6, "2606:4700::1"), (socket.AF_INET, "104.26.0.171")),
    )
    net_prefs.force_ipv4(True)

    assert socket.getaddrinfo("x", 443, socket.AF_INET6)[0][0] == socket.AF_INET6


def test_force_ipv4_is_idempotent_and_reversible(net_prefs, monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        _fake_getaddrinfo((socket.AF_INET6, "::1"), (socket.AF_INET, "1.1.1.1")),
    )
    original = socket.getaddrinfo

    net_prefs.force_ipv4(True)
    once = socket.getaddrinfo
    net_prefs.force_ipv4(True)
    assert socket.getaddrinfo is once, "double install must not nest wrappers"

    net_prefs.force_ipv4(False)
    assert socket.getaddrinfo is original
    assert len(socket.getaddrinfo("x", 443)) == 2


def test_bot_applies_ipv4_preference_from_settings():
    source = (ROOT / "minecraft_main.py").read_text(encoding="utf-8")

    assert "import net_prefs" in source
    assert "ForceIPv4" in source
    # Applied both at bot start and on hot-reload, so the toggle is live.
    assert source.count("net_prefs.apply_setting(") == 2
