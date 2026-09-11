# TikTokLive empty-JSON reconnect loop

## Symptom

The bot repeatedly prints:

```text
Disconnected unexpectedly: Expecting value: line 1 column 1 (char 0)
Reconnecting...
```

This generic `JSONDecodeError` does **not** identify the failing boundary. Do not assume the username, Euler signer, WebSocket, or a recently added unrelated feature caused it.

## Investigation order

1. Confirm the production username from the **release runtime config**, not the source config. Deploys intentionally preserve `release/config/`; source and release may differ.
2. Probe room resolution independently:
   - `fetch_room_id_from_html`
   - `fetch_room_id_from_api`
3. Probe `fetch_gift_list()` independently.
4. Probe `fetch_signed_websocket(...)` independently with the production Euler API key and host.
5. Test against a user known to be live, adding a temporary `ConnectEvent` listener. A process merely staying alive is insufficient proof; require `ConnectEvent` and its room ID.
6. Compare the installed/build-time TikTokLive version with `requirements.txt`. PyInstaller uses the active environment, so a stale or alpha package can be bundled even when requirements claims another version.

## Confirmed failure pattern

TikTokLive's preliminary bulk/live-status check can return an empty body and attempt `response.json()`, causing the generic error before the otherwise healthy room/signing/WebSocket path completes.

When room resolution and signing are independently healthy, a narrow bypass is:

```python
client.run(fetch_gift_info=True, fetch_live_check=False)
```

This skips only the unreliable preflight. It does not disable room resolution, signed WebSocket connection, or event delivery.

## Verification

Test both paths against a known-live account:

```python
@client.on(ConnectEvent)
async def connected(event):
    print(f"CONNECTED room_id={event.room_id}", flush=True)

client.run(fetch_gift_info=True, fetch_live_check=False)
```

A successful fix requires the `CONNECTED` line, not merely absence of an exception.

## Logging improvement

Reconnect logs should include exception type:

```python
print(f"Disconnected unexpectedly [{type(exc).__name__}]: {exc}")
```

When debug mode is enabled, print the complete traceback. One-line reconnect loops otherwise erase the component boundary needed for diagnosis.

## Pitfall

Never mutate production TikTok usernames based solely on a source/release config mismatch. First validate each candidate through room resolution and respect the user's statement about which account is production versus test-only.
