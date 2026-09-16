"""Tests for the optional Minecraft chat feedback mirror.

Covers:
  - default config ships the mc_feedback block (enabled=False)
  - the mirror is OFF by default and does not touch Minecraft
  - per-type gating (success / error / denied)
  - tellraw command is valid, single-line JSON, escaped against injection
  - a dead Minecraft connector never breaks the overlay toast
  - custom prefix is honored and empty prefix falls back to [Music]
  - live config read (flip enabled without restart)

Run (Windows interpreter that has mcrcon):
    C:\\Python313\\python.exe test_song_mc_feedback.py
"""

import json
import os
import sys
import shutil
import importlib
import traceback

# Resolve project root so `import spotify_handler` works from anywhere.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import spotify_handler as sh

# ── Sandbox: NEVER touch real runtime files ───────────────────────────────────
# Copy the real file aside, point CONFIG_FILE/FEEDBACK_FILE/QUEUE_FILE at temp
# paths, and restore on exit. A test must never delete a live config.
_REAL_PATHS = {}
_tmpdir = None


def _sandbox_install():
    import tempfile

    global _tmpdir
    _tmpdir = tempfile.mkdtemp(prefix="songmcfb_test_")
    for name in ("CONFIG_FILE", "FEEDBACK_FILE", "QUEUE_FILE", "HISTORY_FILE"):
        real = getattr(sh, name)
        _REAL_PATHS[name] = real
        tmp = os.path.join(_tmpdir, os.path.basename(real))
        if os.path.exists(real):
            try:
                with open(real, "rb") as src, open(tmp, "wb") as dst:
                    dst.write(src.read())
            except OSError:
                pass
        setattr(sh, name, tmp)


def _sandbox_restore():
    for name, real in _REAL_PATHS.items():
        setattr(sh, name, real)
    if _tmpdir and os.path.isdir(_tmpdir):
        shutil.rmtree(_tmpdir, ignore_errors=True)


# ── Test doubles ──────────────────────────────────────────────────────────────

_SENT_COMMANDS = []
_REAL_SEND = None
_REAL_SEND_SYNC = None


def _install_fake_sender():
    """Replace minecraft_main's senders with capture stubs.

    The mirror calls the sync twin; the async one is patched too so any future
    caller is covered. Captures into the module-level _SENT_COMMANDS list.
    """
    global _REAL_SEND, _REAL_SEND_SYNC
    import minecraft_main

    if _REAL_SEND is None:
        _REAL_SEND = minecraft_main.send_minecraft_command
    if _REAL_SEND_SYNC is None:
        _REAL_SEND_SYNC = getattr(
            minecraft_main, "send_minecraft_command_sync", None)
    minecraft_main.send_minecraft_command = lambda cmd: _SENT_COMMANDS.append(cmd)
    if _REAL_SEND_SYNC is not None:
        minecraft_main.send_minecraft_command_sync = (
            lambda cmd: _SENT_COMMANDS.append(cmd))


def _restore_sender():
    import minecraft_main

    if _REAL_SEND is not None:
        minecraft_main.send_minecraft_command = _REAL_SEND
    if _REAL_SEND_SYNC is not None:
        minecraft_main.send_minecraft_command_sync = _REAL_SEND_SYNC


def _fresh_sender():
    """Reset and re-stub the sender; returns the capture list."""
    del _SENT_COMMANDS[:]
    _install_fake_sender()
    return _SENT_COMMANDS


# Pytest fixture: every test gets a sandboxed config + captured commands,
# and the real paths are restored no matter how the test ends.
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    _sandbox_install()
    _install_fake_sender()
    del _SENT_COMMANDS[:]
    yield
    _restore_sender()
    _sandbox_restore()


def _write_config(mc_feedback):
    with open(sh.CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"enabled": True, "mc_feedback": mc_feedback}, f, indent=2)


# ── Assertions ────────────────────────────────────────────────────────────────

class _Fail(Exception):
    pass


def check(name, cond, extra=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name} {extra}")
        raise _Fail(name)


def test_default_config_has_mc_feedback():
    cfg = sh.get_default_config()
    check("default has mc_feedback key", "mc_feedback" in cfg)
    mcf = cfg.get("mc_feedback") or {}
    check("default enabled is False", mcf.get("enabled") is False, str(mcf))
    check("default notify_success True", mcf.get("notify_success") is True)
    check("default notify_errors True", mcf.get("notify_errors") is True)
    check("default notify_denied True", mcf.get("notify_denied") is True)
    check("default prefix [Music]", mcf.get("prefix") == "[Music]")


def test_disabled_by_default_sends_nothing():
    del _SENT_COMMANDS[:]
    _write_config({"enabled": False, "notify_success": True})
    sh.push_song_feedback("koolguy99", "success", "✓",
                          "@koolguy99 queued Song — Artist")
    check("no tellraw when disabled", len(_SENT_COMMANDS) == 0, str(_SENT_COMMANDS))


def test_enabled_success_sends_tellraw():
    del _SENT_COMMANDS[:]
    _write_config({"enabled": True, "notify_success": True})
    sh.push_song_feedback("koolguy99", "success", "✓",
                          "@koolguy99 queued Song — Artist",
                          "Position #1 • Use !pull to remove your request")
    check("one command sent", len(_SENT_COMMANDS) == 1, str(_SENT_COMMANDS))
    cmd = _SENT_COMMANDS[0]
    check("is tellraw @a", cmd.startswith("tellraw @a ["), cmd)
    check("no raw newlines", "\n" not in cmd and "\r" not in cmd)
    check("valid JSON tail", cmd.rstrip().endswith("]"))
    check("green for success", '"color":"green"' in cmd, cmd)
    check("prefix present", "[Music]" in cmd, cmd)
    check("leading @ stripped", '"@koolguy99' not in cmd, cmd)
    check("nick present", "koolguy99" in cmd, cmd)
    check("detail present", "Use !pull" in cmd, cmd)

    # JSON payload must parse — proves escaping is correct, not just eyeballed.
    payload = cmd[len("tellraw @a "):].strip()
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as e:
        check("tellraw payload parses as JSON", False, f"{e} :: {payload!r}")
        return
    check("tellraw payload parses as JSON", True)
    check("payload is a list", isinstance(parsed, list) and len(parsed) == 4)


def test_error_and_denied_types():
    del _SENT_COMMANDS[:]
    _write_config({"enabled": True, "notify_errors": True, "notify_denied": True})
    sh.push_song_feedback("badguy", "error", "✗", "@badguy — no results for \"x\"")
    check("error sent", len(_SENT_COMMANDS) == 1, str(_SENT_COMMANDS))
    check("red for error", '"color":"red"' in _SENT_COMMANDS[0], _SENT_COMMANDS[0])

    del _SENT_COMMANDS[:]
    sh.push_song_feedback("noob", "denied", "⊘", "@noob — level too low to skip")
    check("denied sent", len(_SENT_COMMANDS) == 1, str(_SENT_COMMANDS))
    check("gold for denied", '"color":"gold"' in _SENT_COMMANDS[0], _SENT_COMMANDS[0])


def test_per_type_gating():
    del _SENT_COMMANDS[:]
    _write_config({"enabled": True, "notify_success": False,
                   "notify_errors": True, "notify_denied": False})
    sh.push_song_feedback("a", "success", "✓", "@a queued X")
    sh.push_song_feedback("b", "error", "✗", "@b fail")
    sh.push_song_feedback("c", "denied", "⊘", "@c denied")
    # Only the error type is enabled → exactly one command, and it's the error.
    check("only error type sent", len(_SENT_COMMANDS) == 1, str(_SENT_COMMANDS))
    check("it was the error", '"color":"red"' in _SENT_COMMANDS[0],
          _SENT_COMMANDS[0])

    del _SENT_COMMANDS[:]
    _write_config({"enabled": True, "notify_success": True, "notify_denied": True})
    sh.push_song_feedback("a", "success", "✓", "@a queued X")
    sh.push_song_feedback("c", "denied", "⊘", "@c denied")
    check("two sent when types enabled", len(_SENT_COMMANDS) == 2, str(_SENT_COMMANDS))

    del _SENT_COMMANDS[:]
    _write_config({"enabled": True, "notify_errors": False,
                   "notify_success": False, "notify_denied": False})
    sh.push_song_feedback("a", "success", "✓", "@a queued X")
    sh.push_song_feedback("b", "error", "✗", "@b fail")
    sh.push_song_feedback("c", "denied", "⊘", "@c denied")
    check("all types off → silence", len(_SENT_COMMANDS) == 0,
          str(_SENT_COMMANDS))


def test_dead_minecraft_never_breaks_toast():
    """A Minecraft connector that throws must not break push_song_feedback."""
    import minecraft_main

    del _SENT_COMMANDS[:]

    def boom(cmd):
        raise ConnectionRefusedError("RCON down")

    # The mirror calls the SYNC twin — break that one, not just the async one.
    orig_sync = getattr(minecraft_main, "send_minecraft_command_sync", None)
    minecraft_main.send_minecraft_command_sync = boom
    try:
        _write_config({"enabled": True, "notify_success": True})
        # Must not raise — the toast is the primary feedback channel.
        sh.push_song_feedback("koolguy99", "success", "✓",
                              "@koolguy99 queued Song — Artist")
        check("toast survived dead connector", True)
    finally:
        if orig_sync is not None:
            minecraft_main.send_minecraft_command_sync = orig_sync


def test_custom_and_empty_prefix():
    del _SENT_COMMANDS[:]
    _write_config({"enabled": True, "notify_success": True, "prefix": "[Jams]"})
    sh.push_song_feedback("u", "success", "✓", "@u queued X")
    check("custom prefix used", "[Jams]" in _SENT_COMMANDS[0], _SENT_COMMANDS[0])
    check("default prefix not used", "[Music]" not in _SENT_COMMANDS[0],
          _SENT_COMMANDS[0])

    del _SENT_COMMANDS[:]
    _write_config({"enabled": True, "notify_success": True, "prefix": "   "})
    sh.push_song_feedback("u", "success", "✓", "@u queued X")
    check("blank prefix falls back", "[Music]" in _SENT_COMMANDS[0],
          _SENT_COMMANDS[0])


def test_escape_against_injection():
    del _SENT_COMMANDS[:]
    _write_config({"enabled": True, "notify_errors": True})
    # A malicious / accidental title containing a quote and a tellraw break-out.
    sh.push_song_feedback(
        "evil", "error", "✗",
        '@evil — no results for "} , {"text":"ADMIN","color":"red"'
    )
    check("injection attempt sent", len(_SENT_COMMANDS) == 1, str(_SENT_COMMANDS))
    cmd = _SENT_COMMANDS[0]
    payload = cmd[len("tellraw @a "):].strip()
    try:
        json.loads(payload)
    except json.JSONDecodeError as e:
        check("injected payload still valid JSON", False, f"{e} :: {payload!r}")
        return
    check("injected payload still valid JSON", True)
    # The escaped backslash sequence must be present, not a raw break-out.
    check("quote escaped", '\\"' in payload, payload)


def test_live_config_read():
    """Flipping enabled must take effect on the next call (no restart)."""
    del _SENT_COMMANDS[:]
    _write_config({"enabled": True, "notify_success": True})
    sh.push_song_feedback("u", "success", "✓", "@u queued X")
    n_on = len(_SENT_COMMANDS)
    _write_config({"enabled": False, "notify_success": True})
    sh.push_song_feedback("u", "success", "✓", "@u queued X")
    n_off = len(_SENT_COMMANDS)
    check("sent while enabled", n_on == 1, f"n_on={n_on}")
    check("silenced after config flip", n_off == n_on, f"n_off={n_off}")


# ── Runner ───────────────────────────────────────────────────────────────────

def main():
    _sandbox_install()
    _install_fake_sender()
    tests = [
        test_default_config_has_mc_feedback,
        test_disabled_by_default_sends_nothing,
        test_enabled_success_sends_tellraw,
        test_error_and_denied_types,
        test_per_type_gating,
        test_dead_minecraft_never_breaks_toast,
        test_custom_and_empty_prefix,
        test_escape_against_injection,
        test_live_config_read,
    ]
    failed = []
    try:
        for t in tests:
            print(f"\n[TEST] {t.__name__}")
            try:
                t()
            except _Fail as e:
                failed.append(str(e))
            except Exception:
                failed.append(t.__name__)
                traceback.print_exc()
    finally:
        _restore_sender()
        _sandbox_restore()

    print("\n" + "=" * 54)
    if failed:
        print(f"FAILED ({len(failed)}): {', '.join(failed)}")
        sys.exit(1)
    print(f"ALL {len(tests)} PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
