# Timer Reset Pattern — Live Duration Should Restart on New Stream

**Problem:** Live duration text was resuming from previous live session instead of resetting to 0 when connecting to a NEW stream. Timer accumulated across disconnected streams, making the UI misleading ("5:23" after a fresh connect).

**Root Cause:** Timer state (`_timerState.totalElapsedSec`) persisted indefinitely and only accumulated time without any reset trigger. On reconnect (even to same room), it kept adding elapsed seconds. No logic distinguished "reconnect to same stream" vs "connect to new stream".

**Solution Implemented (2026-08-13):**

1. **Track first-connect flag:** Added `startedNewStream` field to `_timerState` object to detect initial connection.

2. **Reset on stop/restart:** When user clicks Stop Bot, clear all timer state:
   ```javascript
   async function stopBot() {
     // ...stop logic...
     // Reset timer state on stop so new streams start from 0
     _timerState.totalElapsedSec = 0;
     streamStartTime = null;
     _timerState.startedNewStream = false;
     document.getElementById('stream-timer').textContent = '--:--:--';
   }
   ```

3. **Smart resume logic:** In `resumeTimerWhenConnected()`:
   - **First connect OR new stream:** Reset to 0, set `streamStartTime = Date.now()`
   - **Reconnect to same stream:** Accumulate time from last disconnect (nice-to-have for network glitches)
   ```javascript
   if (!_timerState.startedNewStream || !streamStartTime) {
     _timerState.totalElapsedSec = 0;
     streamStartTime = Date.now();
     _timerState.startedNewStream = true;
   } else {
     const now = Date.now();
     const accumulated = Math.floor((now - streamStartTime) / 1000);
     _timerState.totalElapsedSec += accumulated;
     streamStartTime = now;
   }
   ```

**Behavior:**
- ✅ Each Stop→Start cycle resets timer to `00:00:00`
- ✅ Brief reconnects (same room, <60s gap) accumulate time gracefully
- ❌ Extended disconnections (>60s) are treated as new streams (reset to 0)

**Frontend Integration:** Status text updates read `meta.settings.LogOnlyMode` AND control timer state via `updateBotStatusUI(isRunning, meta)`. Timer starts ONLY when `state === 'connected'`, never on "connecting"/"starting".

**Pitfalls:**
- Don't persist timer state across manual stops — user expects fresh count each time
- Don't use button-click heuristics — trust socket lifecycle events (ConnectEvent fires once per real connection)
- Always validate state_time delta before allowing transitions to prevent flappy UI

**Related fixes in same session:**
- `/api/bot/status` must return `settings` dict with `LogOnlyMode`, `DebugMode` values
- Path resolution mismatch between dashboard/source and bot/release directories
- Terminal states (`connected`, `disconnected`, `ended`, `stopped`) should NEVER be treated as stale — only transient states (`starting`, `connecting`, `reconnecting`) get staleness checks

**Test pattern:** Start bot → watch timer increment → Stop bot → verify reset to `--:--:--` → Start again → verify fresh count from 0.

*Captured 2026-08-13 during LogOnlyMode debugging session.*