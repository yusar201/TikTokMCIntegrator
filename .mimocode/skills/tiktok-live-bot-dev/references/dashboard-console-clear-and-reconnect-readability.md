# Dashboard console clearing and reconnect readability

## Bot console Clear must clear the source, not only the DOM

The dashboard's **Console** is backed by the dashboard process's in-memory `bot_logs` list and polled from `GET /api/bot/logs`. A UI-only clear such as:

```js
terminal.textContent = '';
lastLogCount = 0;
```

is not a real clear: the next poll retrieves the unchanged server list and repaints every line.

Correct vertical slice:

1. Add `POST /api/bot/logs/clear`.
2. Clear `bot_logs` while holding `_bot_logs_lock`.
3. Make `clearConsole()` await that endpoint, then update the terminal placeholder and reset `lastLogCount`.
4. Bump the dashboard JS cache-bust version.
5. Regression-test POST clear followed by GET logs returning `{"logs": []}`.

Do not confuse this with the separate Minecraft Sim Console, which is file-backed by `logs/sim_console.log` and uses `/api/console/logs` plus `/api/console/clear`.

## Reconnect policy and operator-facing output

Current intended policy for failed TikTok startup or a mid-stream drop:

- First retry: **5 seconds**.
- Backoff: `1.5x + random jitter from 0–2 seconds`.
- Maximum delay: **300 seconds / 5 minutes**.
- Maximum consecutive failures: **20 attempts**, then stop.
- A genuine `LiveEndEvent` is a clean stop and must not reconnect.
- A successful reconnect resets the next-drop delay to 5 seconds.

Keep internal jitter, but never print raw floats such as `4.981727281 seconds`. Convert the operator-facing duration to a safe whole-second value, preferably rounding upward so the message does not promise an earlier retry than the actual sleep. Connection failures must be actionable in normal production mode, not only when Debug Mode is enabled. The operator console must always include:

- attempt count and exception type/message;
- the complete traceback/exception chain, including the exact TikTokLive route and parser line;
- for HTTP/JSON failures, a sanitized response summary when available: endpoint without query parameters, status, content type, byte count, and a bounded/redacted body preview;
- the clean reconnect delay.

Never dump traceback frame locals, signed query strings, cookies, API keys, or authorization headers. Debug Mode may gate noisy event probes, but it must never hide crash diagnostics.

Good output shape:

```text
TikTok connection failure (1/20)
Exception: JSONDecodeError: ...
Failing HTTP response:
  endpoint=https://.../gift/list/
  status=200
  content_type=text/html
  bytes=0
  body_preview=<empty>
Full traceback:
...
Reconnecting in 5 seconds...
```

Use small pure helper modules for diagnostics and delay formatting/backoff so behavior is testable without importing the event-heavy bot module. Test exception chaining, exact call-site visibility, sanitized HTTP context, secret redaction, formatting, the 1.5x progression, and the 300-second cap. Preserve the actual reconnect architecture; this is an observability/readability fix, not a reason to replace or flatten the backoff.
