# TikTok Bot Reconnect Loop, Backoff, and Operator-Facing Logs

## Current contract

TikTokLive's `client.run()` may either raise on a network failure **or return without raising** after a mid-stream heartbeat/drop. A clean return is therefore not enough to prove that the streamer ended the LIVE.

Use a module-level `_stream_ended_cleanly` flag set only by `LiveEndEvent`. After `client.run()` returns:

- `_stream_ended_cleanly == True` → stop permanently.
- Otherwise → treat it as a dropped connection and retry.
- Dashboard Stop remains external process termination and bypasses the loop.

## Retry policy

The established TikTokMCIntegrator policy is:

- First retry: **5 seconds**.
- Backoff: `ceil(current * 1.5 + jitter)`.
- Jitter: random **0–2 seconds**.
- Cap: **300 seconds / 5 minutes**.
- Limit: **20 failed attempts**, then shut down.
- After a successful reconnect, reset the next-drop delay to 5 seconds.

Keep the numeric sleep value and displayed value separate. Internally, jitter may be fractional; dashboard logs must use human-readable whole seconds:

```python
import math


def format_reconnect_delay(delay: float) -> str:
    seconds = max(1, int(math.ceil(delay)))
    unit = "second" if seconds == 1 else "seconds"
    return f"{seconds} {unit}"


def next_reconnect_delay(current: float, jitter: float) -> int:
    return min(int(math.ceil(current * 1.5 + jitter)), 300)
```

Good: `Reconnecting in 5 seconds...`

Bad: `Reconnecting in 4.981727281 seconds...`

The precise float is implementation noise and makes an operator console look broken.

## Loop invariants

Both failure modes — exception and return-without-LiveEnd — must:

1. Increment the failure attempt.
2. Log the attempt count and current wait cleanly.
3. Sleep for the current delay.
4. Advance to the next backoff delay.
5. Stop after the attempt limit.

Avoid duplicating the retry block if a small helper can keep the branches equivalent.

## Data preservation

On `ConnectEvent`, compare the current `client.room_id` to persisted stream state:

- Same room ID → reconnect to the same stream; preserve gift/chat/follow/superfan logs and counters.
- Different room ID → fresh stream; reset stream-scoped state.

Use the project's `paths.data(...)` helpers for state files. Do not use bare relative paths in a frozen build.

## Tests

Extract formatting/backoff arithmetic into a tiny pure module so tests do not import the entire TikTok client/event-handler module.

Required regression assertions:

- `format_reconnect_delay(4.981727281) == "5 seconds"`.
- Singular formatting for 1 second.
- `5` seconds advances to `8–10` depending on jitter.
- Delay caps at 300 seconds.
- Both `client.run()` return-without-LiveEnd and exception paths route to retry.

## PyInstaller pitfall

A helper imported only inside `run_bot()` may be missed by PyInstaller analysis, especially when the bot module itself is reached through a runtime `--run-bot` branch. Add the helper to the active `.spec` `hiddenimports` and verify it in `build/<app>/Analysis-00.toc` or `PYZ-00.toc` after a full build.

Checking only `base_library.zip` is insufficient: application modules normally live in the PYZ archive.

## Pitfalls

- Do not interpret every normal `client.run()` return as stream end.
- Do not clear stream logs on same-room reconnect.
- Do not expose raw jitter floats in operator-facing logs.
- Do not retry forever without a cap and attempt limit.
- Do not claim a helper is bundled until the PyInstaller TOC proves it.
