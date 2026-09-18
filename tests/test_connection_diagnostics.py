"""Connection-diagnostics + latency contracts.

Covers the three fixes for "connects, then events stale / commands don't run on
a flaky link":
  1. the bot's console output survives the app closing (it used to live only in
     an in-memory list, so a past session could not be diagnosed afterwards);
  2. the automatic gift-catalog sync no longer fires on EVERY connect/reconnect
     (it is ~48 HTTP requests with a 45s timeout, and a flapping connection used
     to re-run the whole burst on every reconnect);
  3. the app-side event latency floor (bot flush interval + dashboard poll) is
     lowered.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


# ── 1. bot console persistence ───────────────────────────────────────────────

class _FakePipe:
    def __init__(self, lines):
        self._lines = list(lines)

    def readline(self):
        return self._lines.pop(0) if self._lines else ''


def test_bot_console_output_is_persisted_to_a_file(monkeypatch, tmp_path):
    import app as module

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    monkeypatch.setattr(module.paths, 'logs', lambda name: str(logs_dir / name))
    monkeypatch.setattr(module, 'bot_process', None)
    monkeypatch.setattr(module, 'bot_logs', [])

    module.read_output(_FakePipe(["Connected to @viplalicer\n",
                                  "Connection dropped (run returned, 1/20).\n"]))

    written = (logs_dir / "bot_console.log").read_text(encoding="utf-8")
    assert "Connected to @viplalicer" in written
    assert "Connection dropped (run returned, 1/20)." in written


def test_bot_console_persistence_never_breaks_the_reader(monkeypatch, tmp_path):
    """A logging failure must not cost the dashboard its live console lines."""
    import app as module

    def _boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(module, 'append_bot_console_line', _boom)
    monkeypatch.setattr(module, 'bot_process', None)
    monkeypatch.setattr(module, 'bot_logs', [])

    module.read_output(_FakePipe(["keep me\n"]))

    assert "keep me" in module.bot_logs


# ── 2. automatic catalog sync guard ──────────────────────────────────────────

def test_auto_sync_runs_when_never_synced(tmp_path):
    from gift_catalog_sync import should_run_auto_sync

    assert should_run_auto_sync(tmp_path / "sync_state.json") is True


def test_auto_sync_skipped_within_interval_after_success(tmp_path):
    from gift_catalog_sync import (
        should_run_auto_sync, record_auto_sync, AUTO_SYNC_MIN_INTERVAL_HOURS,
    )

    state = tmp_path / "sync_state.json"
    now = 1_700_000_000.0
    record_auto_sync(state, ok=True, now=now)

    assert should_run_auto_sync(state, now=now + 1) is False
    assert should_run_auto_sync(state, now=now + AUTO_SYNC_MIN_INTERVAL_HOURS * 3600 - 1) is False
    assert should_run_auto_sync(state, now=now + AUTO_SYNC_MIN_INTERVAL_HOURS * 3600 + 1) is True


def test_auto_sync_retries_sooner_after_a_failure(tmp_path):
    from gift_catalog_sync import (
        should_run_auto_sync, record_auto_sync, AUTO_SYNC_FAILURE_RETRY_MINUTES,
    )

    state = tmp_path / "sync_state.json"
    now = 1_700_000_000.0
    record_auto_sync(state, ok=False, now=now)

    assert should_run_auto_sync(state, now=now + 30) is False
    assert should_run_auto_sync(state, now=now + AUTO_SYNC_FAILURE_RETRY_MINUTES * 60 + 1) is True


def test_auto_sync_survives_a_corrupt_state_file(tmp_path):
    from gift_catalog_sync import should_run_auto_sync

    state = tmp_path / "sync_state.json"
    state.write_text("{not json", encoding="utf-8")

    assert should_run_auto_sync(state) is True


# ── 2b. the claim primitive: reserve BEFORE the work starts ──────────────────

def test_claim_auto_sync_reserves_the_slot_up_front(tmp_path):
    from gift_catalog_sync import claim_auto_sync

    state = tmp_path / "sync_state.json"

    assert claim_auto_sync(state) is True
    # The slot is taken the moment it is claimed, not when the work finishes.
    assert claim_auto_sync(state) is False


def test_interrupted_sync_still_gates_the_next_connect(tmp_path):
    """Closing the app mid-sync must not re-arm the whole burst.

    Regression: the attempt used to be recorded only in the sync's `finally`, so
    killing the app during the ~48-request run left no state file and the next
    connect re-ran it — the exact amplification the gate exists to prevent.
    """
    from gift_catalog_sync import claim_auto_sync, AUTO_SYNC_FAILURE_RETRY_MINUTES

    state = tmp_path / "sync_state.json"
    now = 1_700_000_000.0

    assert claim_auto_sync(state, now=now) is True
    # ...app closed here: _sync_gift_regions_once never reaches its finally...
    assert claim_auto_sync(state, now=now + 60) is False
    assert claim_auto_sync(state, now=now + AUTO_SYNC_FAILURE_RETRY_MINUTES * 60 + 1) is True


def test_connect_handler_claims_the_sync_slot(tmp_path):
    """The connect path must reserve via the claim primitive, not check-then-run."""
    source = (ROOT / "minecraft_main.py").read_text(encoding="utf-8")

    assert "claim_auto_sync" in source
    assert "gift_catalog_sync.AUTO_SYNC_STATE_FILENAME" in source
    # A plain check-then-schedule is the race the claim primitive replaced.
    assert "should_run_auto_sync(paths.data(" not in source


# ── 1b. persisted console lines carry a timestamp ────────────────────────────

def test_persisted_console_lines_are_timestamped(monkeypatch, tmp_path):
    import re
    import app as module

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    monkeypatch.setattr(module.paths, 'logs', lambda name: str(logs_dir / name))
    monkeypatch.setattr(module, 'bot_process', None)
    monkeypatch.setattr(module, 'bot_logs', [])

    module.read_output(_FakePipe(["Connection dropped (run returned, 1/20).\n"]))

    written = (logs_dir / "bot_console.log").read_text(encoding="utf-8")
    stamp = re.search(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", written)
    assert stamp, written
    # Without per-line times the drop history cannot be timed after the fact.
    assert re.search(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] Connection dropped", written)


def test_in_memory_console_stays_unstamped(monkeypatch, tmp_path):
    """The dashboard console shows the bot's own text — no added prefix."""
    import app as module

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    monkeypatch.setattr(module.paths, 'logs', lambda name: str(logs_dir / name))
    monkeypatch.setattr(module, 'bot_process', None)
    monkeypatch.setattr(module, 'bot_logs', [])

    module.read_output(_FakePipe(["plain bot line\n"]))

    assert module.bot_logs == ["plain bot line"]


# ── 3. lowered app-side latency floor ────────────────────────────────────────

def test_bot_flush_interval_is_lowered():
    source = (ROOT / "minecraft_main.py").read_text(encoding="utf-8")

    assert "LOG_FLUSH_INTERVAL = 1.0" in source


@pytest.mark.parametrize("call", ["fetchChatLog, 1500", "fetchGiftLog, 1500"])
def test_dashboard_event_polls_are_faster(call):
    script = (ROOT / "static" / "script.js").read_text(encoding="utf-8")

    assert call in script
    assert "scheduleLightPoll(fetchChatLog, 2500)" not in script
