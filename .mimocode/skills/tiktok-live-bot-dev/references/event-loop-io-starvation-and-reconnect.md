# Event-Loop I/O Starvation → Disconnect Death-Spiral (+ reconnect-loop bug)

Discovered 2026-06-23 debugging "bot keeps disconnecting on a big streamer
(20k viewers, heavy chat)". Two distinct bugs, both in `minecraft_main.py`.

## Bug 1 — synchronous per-event disk I/O on the asyncio event loop

The TikTok event handlers (`@client.on(CommentEvent)`, GiftEvent, FollowEvent,
SuperFanEvent…) run ON the asyncio event loop. The append_*_log helpers did a
full **read-modify-write of the ENTIRE json log file PER event**:

```python
with _log_lock:
    entries = load_json(log_file, [])   # read + parse whole file
    entries.append(entry)               # add one
    safe_json_write(entries, log_file)  # re-serialize + write whole array
```

Cost is O(N) per event, O(N²) over a stream. On a high-volume stream the chat
flood made each write block the event loop long enough to **miss the TikTokLive
websocket heartbeat → TikTok drops the connection**. Reconnect preserved the
(now huge) `chat_log.json`, so it disconnected again *faster* → death spiral.
Why it only bites on big streams: small stream = tiny file = fast writes = loop
never starves.

### Fix — in-memory buffer + background flush thread

- Event handlers call `_buffer_append(log_file, entry)` → O(1) in-memory list
  append, **zero disk in the hot path**.
- A daemon thread (`_log_flush_worker`, started once via `_start_log_flusher()`
  from `on_connect`) flushes all dirty buffers to disk every `LOG_FLUSH_INTERVAL`
  (2.0s) — one batched write per file, OFF the event loop.
- Flush snapshots dirty buffers under a short lock, then writes outside the lock
  so slow disk I/O never blocks event-loop appends.
- `on_connect`: fresh session → `_buffer_clear(f, [])` (resets buffer AND disk);
  reconnect → `_buffer_init(f, [])` (loads preserved on-disk entries into the
  buffer so the flusher doesn't overwrite them with an empty array).
- `on_disconnect` and `on_live_end` call `_flush_buffers_once()` so nothing
  buffered is lost on a drop.

Dashboard is unaffected — it reads the json files via `routes/stats.py`, just
sees them refreshed every ~2s instead of per-message. Post-stream reports
unaffected. Verified with a local sim: 20k concurrent appends vs a live flusher,
zero loss/corruption; 10k appends in ~1.6ms.

**Rule:** NEVER do synchronous file I/O (or any blocking call) inside an async
TikTok event handler. Buffer in memory, flush from a background thread.

## Bug 2 — reconnect loop treated a mid-stream drop as "stream ended"

`client.run(fetch_gift_info=True)` **returns normally** on a mid-stream
heartbeat drop — it does NOT raise. The old loop assumed a normal return meant
the stream ended:

```python
client.run(fetch_gift_info=True)
print("Stream ended. Bot shutting down.")
break   # <-- WRONG: also fires on a silent drop, bot dies instead of reconnecting
```

So "sudden disconnects that never come back" were this: the bot exited instead
of retrying.

### Fix — distinguish real end (LiveEndEvent) from a drop

- `LiveEndEvent` (import from `TikTokLive.events`) fires only when the streamer
  actually ends the live. `DisconnectEvent` fires on any drop.
- Add a module global `_stream_ended_cleanly = False`; the `@client.on(LiveEndEvent)`
  handler sets it True.
- In `run_bot()`: after `client.run()` returns, `break` ONLY if
  `_stream_ended_cleanly`; otherwise treat it as a drop and reconnect with the
  same exponential backoff used in the `except` branch. Reset `reconnect_delay`
  to 5 on a successful reconnect so the next drop starts fresh.

## TikTokLive event vocabulary (verified present in this version)

`AccessControlEvent, ControlEvent, DisconnectEvent, LiveEndEvent,
LiveGameIntroEvent, LiveIntroEvent, LivePauseEvent, LiveUnpauseEvent,
OecLiveShoppingEvent` — confirm with:
`python3 -c "from TikTokLive import events; print(dir(events))"`.

## Verifying buffer/flush logic without a live connection

Import the real functions from `minecraft_main` (creating the client object at
import does NOT open a socket — only `.run()` does) and exercise
append→flush→disk, reconnect-preserve vs fresh-clear, and a concurrency race
(appends on the main thread vs a background flusher). py_compile with
`C:\Python313\python.exe -m py_compile minecraft_main.py` is the correctness
gate before deploy.
