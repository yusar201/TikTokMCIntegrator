# TikTokLive Disconnect Behavior (Library Source Findings)

Discovered 2026-05-26 while investigating mid-stream disconnect. Source: TikTokLive v7 installed on user's Windows Python.

## Key Files Examined

### `TikTokLive/client/client.py`

**`client.run()` → `connect()` → `start()` → `_ws_client_loop()`:**
```python
# line 205-214
def run(self, **kwargs) -> Task:
    """Start a thread-blocking connection to TikTokLive"""
    return self._asyncio_loop.run_until_complete(self.connect(**kwargs))

async def connect(self, callback=None, **kwargs):
    task: Task = await self.start(**kwargs)
    try:
        ...
        await task  # Blocks on _ws_client_loop
    except CancelledError:
        self._logger.debug("The client has been manually stopped with 'client.stop()'.")
    return task
```

**`_ws_client_loop()` — Normal exit path (no exception):**
```python
# line 296-330
async def _ws_client_loop(self, ...):
    async for webcast_response in self._ws.connect(...):
        async for event in self._parse_webcast_response(webcast_response):
            self.emit(event.type, event)

    # When iterator finishes (WebSocket closed cleanly):
    ev: DisconnectEvent = DisconnectEvent()
    self.emit(ev.type, ev)
    # Falls through → function returns → no exception
```

**`handle_custom_event()` — STREAM_ENDED triggers clean disconnect:**
```python
# line 408-417
if isinstance(event, ControlEvent):
    if event.action in {ControlAction.STREAM_ENDED, ControlAction.STREAM_SUSPENDED}:
        # Fire-and-forget disconnect task — does not raise
        self._asyncio_loop.create_task(self.disconnect())
        return LiveEndEvent().parse(response.payload)
    elif event.action == ControlAction.STREAM_PAUSED:
        return LivePauseEvent().parse(response.payload)
```

### `TikTokLive/client/ws/ws_client.py`

**`connect()` — Error exit path (raises exception):**
```python
# line 193-196
# The iterator exits normally when the connection is closed with close code
# 1000 (OK) or 1001 (going away) or without a close code. It raises
# a :exc:`~websockets.exceptions.ConnectionClosedError` when the connection
# is closed with any other code.
```

**Ping timeout pattern:**
```
# line 200-208
# When ping_timeout is set, the client waits for a pong for N seconds.
# TikTok DO NOT SEND pongs back. The websockets client after N seconds
# assumes the server is dead. It then throws:
#   websockets.exceptions.ConnectionClosedError: sent 1011 (unexpected error)
#   keepalive ping timeout; no close frame received
#
# If you set ping_timeout to None, it doesn't wait for a pong.
```

## Conclusion

| Scenario | `client.run()` behavior | Reconnect? |
|----------|------------------------|------------|
| Stream ended (STREAM_ENDED) | Returns cleanly, no exception | ❌ Don't reconnect |
| Network blip / ping timeout | Raises `ConnectionClosedError` | ✅ Reconnect |
| TikTok server kicks connection | Either — depends on close code | ✅ Reconnect (safe) |
| Dashboard Stop button | `subprocess.terminate()` kills process | N/A — process dead before retry |
