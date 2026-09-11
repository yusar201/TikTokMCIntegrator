# Disconnect Death-Spiral on Big Streams — Root Cause & Fix

**Verified 2026-06-23.** Bot kept disconnecting "all of a sudden" while connected to a
large streamer (~20k viewers, heavy chat). Root cause was self-inflicted and architectural.

## Root cause: synchronous disk I/O starves the websocket heartbeat

The TikTok event handlers (`on_comment`, `on_gift`, etc.) run on the **asyncio event loop**.
The old `append_chat_log` / `append_gift_log` / `append_follow_log` / `append_superfan_log`
each did a **full read-modify-write of the entire JSON log file, per event**:

```python
with _log_lock:
    entries = load_json(log_file, [])   # read + parse ENTIRE file
    entries.append(entry)
    safe_json_write(entries, log_file)  # re-serialize + write ENTIRE array
```

That's O(N) per event, O(N²) over the stream. On a chat flood the loop blocks long enough
to miss TikTok's websocket heartbeat → server drops the connection. Reconnect preserves the
(now huge) file → it disconnects again faster → **death spiral**. Only happens on big streams
because small file = fast write = loop never starves.

## Secondary bug: `client.run()` returns normally on a mid-stream drop

`client.run()` does NOT always raise on a heartbeat drop — it can return normally, same as a
real stream end. The old `run_bot()` loop hit `break` ("Stream ended") on any normal return,
so the bot just died instead of reconnecting.

## The fix (two parts)

### 1. In-memory log buffers + background flush thread
Move all per-event disk I/O OFF the event loop:
- Event handlers call `_buffer_append(log_file, entry)` → O(1) in-memory list append, zero disk.
- A daemon thread (`_log_flush_worker`, `LOG_FLUSH_INTERVAL = 2.0s`) batches all dirty buffers
  to disk, one write per file per tick, outside the event loop.
- `_flush_buffers_once()` snapshots dirty buffers under a short lock, then writes outside the
  lock so slow I/O never blocks appends.
- On **fresh session**: `_buffer_clear(f, [])` resets buffer AND disk.
- On **reconnect**: `_buffer_init(f, [])` loads preserved on-disk entries into the buffer so
  the flusher doesn't overwrite them with an empty array.
- `_start_log_flusher()` is idempotent, called from `on_connect`.
- Flush immediately in `on_disconnect` and `on_live_end` so nothing is lost on a drop.

Dashboard keeps reading the JSON files via `routes/stats.py` — just refreshed every ~2s
instead of per-message. Post-stream reports unaffected. Nothing in the bot reads these 4 logs
back mid-stream, so buffering is safe (verify with a grep before assuming).

### 2. Distinguish clean end from drop in the reconnect loop
- Import `LiveEndEvent` from `TikTokLive.events`.
- `@client.on(LiveEndEvent)` sets a module global `_stream_ended_cleanly = True`.
- In `run_bot()`, after `client.run()` returns: if `_stream_ended_cleanly` → `break`
  (real end). Otherwise treat as a drop → reconnect with backoff. Reset backoff to 5s after
  a successful reconnect so the next drop starts fresh.

## Verification without a live stream
Import the real functions from `minecraft_main` (creating the client object at import is fine —
it does NOT open a socket until `.run()`). Exercise: append → flush → read disk; reconnect
`_buffer_init` preserves disk; fresh `_buffer_clear` resets disk; and 20k concurrent appends
against a live flusher thread with zero loss/corruption. Confirmed: 5000 appends wrote zero
bytes to disk; 10k appends in ~1.6ms.

## Generalizable rule
NEVER do synchronous file read-modify-write inside an asyncio event handler that shares the
loop with a heartbeat/websocket. Append to memory in O(1); flush on a background thread. This
is the same class of bug as the live-read-config rule — keep blocking work off the hot path.
