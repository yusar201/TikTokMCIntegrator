"""Per-stream Top Gifters / Top Likers ranking stores.

Two small JSON files hold the current live's leaderboards:

- data/gifter_ranking.json  (coins per gifter)
- data/liker_ranking.json   (likes per liker)

The bot process (minecraft_main) writes them; the Flask dashboard
(routes/stats.py -> /api/stats/topgifter) reads them for the rotating
leaderboard overlay. Both boards reset automatically on every new live
(on_connect fresh-session branch).

Gifts are rare  -> written immediately (force=True).
Likes are bursty -> the in-memory table is authoritative and is flushed to
disk at most once per LIKE_FLUSH_INTERVAL seconds, plus on live end
(flush_all).

The dashboard endpoint may rewrite entry avatars to stable local
/avatar_cache/ URLs and persist them. _merge_entries preserves those local
URLs on the next bot flush so expiring TikTok CDN URLs never regress the
enriched entries.

Manual dashboard reset: the Flask process cannot touch the bot's in-memory
state, so the reset endpoint writes a token file (RESET_TOKEN_FILE); the
bot picks it up on its next update/flush and clears its boards.
"""

import time

import paths
from utils import load_json, save_json

GIFTER_RANKING_FILE = paths.data("gifter_ranking.json")
LIKER_RANKING_FILE = paths.data("liker_ranking.json")
RESET_TOKEN_FILE = paths.data("ranking_reset_token.json")

# Keep enough history so a viewer who falls out of the served top N can
# climb back in with their full accumulated total (likes swing hard).
MAX_STORED = 50
MAX_SERVED = 10
LIKE_FLUSH_INTERVAL = 1.0

_state = {}        # file -> authoritative in-memory entry list
_last_flush = {}   # file -> last disk write timestamp
_last_reset_ts = 0.0
_last_token_check = 0.0

# Manual resets are rare; checking the token file on every like burst
# (hundreds/sec) would hammer the disk. Poll at most this often instead.
TOKEN_CHECK_INTERVAL = 0.5


def _entry_key(entry):
    uid = str(entry.get("unique_id") or "").strip().lower()
    if uid:
        return f"uid:{uid}"
    return f"nick:{str(entry.get('nick') or '').strip().lower()}"


def _local_avatar(url):
    return str(url or "").startswith("/avatar_cache/")


def _merge_entries(in_memory, on_disk):
    """Preserve dashboard avatar enrichments (local URLs) across bot flushes."""
    if not isinstance(on_disk, list) or not on_disk:
        return in_memory
    disk_by_key = {}
    for entry in on_disk:
        if isinstance(entry, dict):
            disk_by_key[_entry_key(entry)] = entry
    for entry in in_memory:
        disk_entry = disk_by_key.get(_entry_key(entry))
        if not disk_entry:
            continue
        mem_url = str(entry.get("avatar_url") or "")
        disk_url = str(disk_entry.get("avatar_url") or "")
        if _local_avatar(disk_url) and not _local_avatar(mem_url):
            entry["avatar_url"] = disk_url
    return in_memory


def _check_reset_token():
    """Clear in-memory boards when the dashboard requested a manual reset.

    Throttled: likes can fire hundreds/sec and each one calls update().
    Polling the token file at most every TOKEN_CHECK_INTERVAL keeps disk
    IO bounded while a dashboard reset still lands within ~0.5s.
    """
    global _last_reset_ts, _last_token_check
    now = time.time()
    if now - _last_token_check < TOKEN_CHECK_INTERVAL:
        return
    _last_token_check = now
    try:
        token = load_json(RESET_TOKEN_FILE, {})
        ts = float(token.get("ts", 0) or 0) if isinstance(token, dict) else 0.0
    except Exception:
        return
    if ts > _last_reset_ts:
        _last_reset_ts = ts
        if ts > 0:
            _state.clear()


def _load(file_path):
    entries = _state.get(file_path)
    if entries is not None:
        return entries
    data = load_json(file_path, [])
    if not isinstance(data, list):
        data = []
    entries = [e for e in data if isinstance(e, dict)]
    _state[file_path] = entries
    return entries


def _flush(file_path, force=False):
    now = time.time()
    if not force and now - _last_flush.get(file_path, 0.0) < LIKE_FLUSH_INTERVAL:
        return
    try:
        entries = _state.get(file_path, [])
        on_disk = load_json(file_path, [])
        merged = _merge_entries(entries, on_disk if isinstance(on_disk, list) else [])
        save_json(file_path, merged[:MAX_STORED])
        _last_flush[file_path] = now
    except Exception as e:
        print(f"[RANKING] Failed writing {file_path}: {e}")


def update(file_path, nick, avatar_url, amount, unique_id="",
           amount_key="total_coins", count_key="gift_count", force=False):
    """Accumulate `amount` for one viewer; board stays sorted desc + capped."""
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return
    if amount <= 0 or not nick:
        return

    _check_reset_token()
    entries = _load(file_path)
    uid = str(unique_id or "").strip().lower()
    nick_l = str(nick).strip().lower()

    found = None
    for entry in entries:
        entry_uid = str(entry.get("unique_id") or "").strip().lower()
        entry_nick = str(entry.get("nick") or "").strip().lower()
        if uid and entry_uid == uid:
            found = entry
            break
        if not uid and not entry_uid and entry_nick == nick_l:
            found = entry
            break
        # Backward compat: old entries stored only the nick.
        if uid and not entry_uid and entry_nick == nick_l:
            found = entry
            break

    if found is None:
        found = {
            "nick": nick,
            "unique_id": uid,
            "avatar_url": avatar_url or "",
            amount_key: 0,
            count_key: 0,
        }
        entries.append(found)

    found["nick"] = nick
    if uid:
        found["unique_id"] = uid
    try:
        found[amount_key] = int(found.get(amount_key, 0)) + amount
    except (TypeError, ValueError):
        found[amount_key] = amount
    try:
        found[count_key] = int(found.get(count_key, 0)) + 1
    except (TypeError, ValueError):
        found[count_key] = 1
    if avatar_url:
        found["avatar_url"] = avatar_url

    entries.sort(key=lambda e: e.get(amount_key, 0) or 0, reverse=True)
    del entries[MAX_STORED:]
    _flush(file_path, force=force)


def top(file_path, amount_key, n=MAX_SERVED):
    """Sorted top-n slice of a board."""
    entries = list(_load(file_path))
    entries.sort(key=lambda e: e.get(amount_key, 0) or 0, reverse=True)
    return entries[:n]


def reset(file_path):
    """Empty one board (new live or bot-side reset)."""
    _state[file_path] = []
    _last_flush.pop(file_path, None)
    try:
        save_json(file_path, [])
    except Exception as e:
        print(f"[RANKING] Failed resetting {file_path}: {e}")


def init_from_disk(file_path):
    """Reconnect to the same live: reload preserved on-disk state."""
    _state.pop(file_path, None)
    _load(file_path)


def ack_reset_token():
    """Baseline the reset-token timestamp WITHOUT clearing the boards.

    Call on connect (fresh or reconnect) so a manual-reset token left over
    from a PREVIOUS live doesn't wipe the new live's first entries.
    """
    global _last_reset_ts
    try:
        token = load_json(RESET_TOKEN_FILE, {})
        ts = float(token.get("ts", 0) or 0) if isinstance(token, dict) else 0.0
        _last_reset_ts = max(_last_reset_ts, ts)
    except Exception:
        pass


def flush_all():
    """Force-write every tracked board (live end / shutdown)."""
    for file_path in list(_state.keys()):
        _flush(file_path, force=True)


def request_reset():
    """Dashboard-side: signal the bot to clear its in-memory boards too.

    The caller clears the on-disk files itself; this token makes the bot
    drop its authoritative in-memory copy on the next update/flush.
    """
    try:
        save_json(RESET_TOKEN_FILE, {"ts": time.time()})
    except Exception as e:
        print(f"[RANKING] Failed writing reset token: {e}")
