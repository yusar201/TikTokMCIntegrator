# Low-Latency Minecraft Command Dispatch

## Symptom

Minecraft commands visibly arrive late during a busy TikTok stream even though there is no explicit application-level RCON queue, lock, semaphore, cooldown, or sleep.

## Hidden queues and pre-dispatch blocking to check

`await asyncio.to_thread(sync_sender, command)` uses asyncio's shared default thread-pool executor. Under concurrent file, HTTP, webhook, asset, or connector work, an RCON call can wait for an executor worker. Awaiting it also keeps that event/action path open until the RCON connection and response complete.

Also inspect everything that runs **before** `execute_actions()` in the TikTok handler. A real rapid alternating-gift regression was caused by completed gifts doing avatar cache network I/O (up to 8 seconds), forced leaderboard JSON writes, awaited SQLite points persistence, and goal/streak JSON writes before global + gift-specific gameplay dispatch. The dashboard gift log could appear first while the actual commands started much later, and accumulated handler pressure could contribute to WebSocket heartbeat loss/reconnects.

For gifts, preserve this boundary:

```text
extract event + atomically update streak delta
→ dispatch global and gift-specific action batches concurrently
→ avatar/ranking/points/goals/streak persistence off the asyncio event loop
```

Keep a separate context snapshot per action batch: global actions retain total `repeat_count`, while immediate streak-delta gift actions receive only `delta`. Do not combine them under one mutable `{amount}` context.

## Raw fire-and-forget pattern

For Khito's stream command path, immediate execution is preferred over backpressure. Start one daemon thread per command and return from the async entrypoint immediately:

```python
async def send_minecraft_command(command):
    threading.Thread(
        target=send_sync_command,
        args=(command,),
        daemon=True,
        name="minecraft-command",
    ).start()
```

The synchronous sender may still select RCON, Forge, or ServerTap. This change is specifically about dispatch latency, not connector selection.

## Important distinctions

- `asyncio.gather()` makes actions within one event concurrent, but does not eliminate the shared executor's internal waiting.
- Opening a fresh `MCRcon(...)` connection per command is direct/raw, but connection setup and the Minecraft server's own main-thread processing still have real latency.
- Do not claim all latency is eliminated: TikTok delivery, network transport, RCON authentication, Mohist tick load, and command execution can still delay visible effects.
- This deliberately allows unbounded concurrency. It matches Khito's stated preference that stream effects execute immediately and that safety throttling is unwanted. Revisit only if measured thread exhaustion or server overload appears.

## Verification

1. Compile changed modules with the packaged Windows Python.
2. AST/static check: the public command entrypoint contains no `await asyncio.to_thread(...)` and starts a thread.
3. Keep the action concurrency regression test: multiple Minecraft actions from one event should begin within a tight time window.
4. Full-build and deploy because the change is Python/backend code.
5. Verify the root release EXE, `_internal/`, no nested release directory, and fresh dist/release timestamps.
6. Restart the released app after successful deployment so the new backend path is loaded.

## Investigation rule

Before changing dispatch, trace the actual path end-to-end:

`TikTok handler -> execute_actions -> _execute_minecraft -> send_minecraft_command -> connector dispatcher -> MCRcon/HTTP`

Search for queues, locks, semaphores, sleeps, cooldowns, executor usage, and sequential awaits at every layer. Distinguish an explicit queue from the implicit shared thread-pool queue.