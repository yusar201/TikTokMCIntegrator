# Toast Feedback Overlay — Sequential Queue Pattern

Pattern for showing transient command feedback as overlays when TikTok comment sending isn't available. One toast at a time, queued sequentially — no stacking, no overlap.

## Problem

Commands like `!play`, `!skip`, `!pull` need user-visible feedback. Sending TikTok comments may not be possible. Showing feedback in Minecraft chat (`tell MC_USERNAME ...`) is invisible to the stream audience. Stacking multiple toasts simultaneously looks cluttered and unreadable in a compact corner overlay.

## Solution: One-at-a-Time Toast Queue

### Architecture

```
Backend (Python)                    Frontend (JS in overlay)
┌─────────────────┐                ┌──────────────────────┐
│ command handler  │                │ handleSong(data) {   │
│   ↓              │                │   const fb = data.   │
│ push_song_       │   poll /api/   │     feedback;        │
│   feedback()  ───┼── stats/song ──┼──→ toastQueue.push(  │
│   ↓              │                │       ...fb);        │
│ deque (max 20)   │                │   processQueue();    │
└─────────────────┘                │ }                    │
                                    │                      │
                                    │ function processQ(){ │
                                    │   if(playing) return;│
                                    │   play next toast    │
                                    │   setTimeout(3.5s)   │
                                    │   → remove → recurse │
                                    │ }                    │
                                    └──────────────────────┘
```

### Backend: Feedback Queue (FILE-BASED, not in-memory)

⚠️ **Critical:** do not use a module-level `deque` for this. The bot runs as a subprocess (see `references/pyinstaller-path-resolution.md`); its in-memory state never reaches Flask. See **§"Sim Works, Real Events Don't"** below for why and the file-based fix.

The bot and Flask must share state via a JSON file on disk — same pattern as `song_queue.json`, `song_history.json`, `song_blocked_uris.json`. Place it next to the exe so the frozen-process `BASE_DIR` resolves it correctly (see `references/pyinstaller-path-resolution.md`).

```python
# spotify_handler.py — file-based bridge
import json, os, threading, tempfile, time
from utils import load_json, save_json  # or implement inline

FEEDBACK_FILE = os.path.join(BASE_DIR, "song_feedback.json")
_fb_lock = threading.Lock()
_FEEDBACK_TTL = 5  # seconds
_MAX_ENTRIES = 50

def _load_feedback():
    if not os.path.exists(FEEDBACK_FILE):
        return []
    try:
        with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError):
        return []

def _save_feedback(entries):
    """Atomic write: temp file + os.replace (cross-platform)."""
    with _fb_lock:
        tmp = FEEDBACK_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
        os.replace(tmp, FEEDBACK_FILE)

def push_song_feedback(nick, fb_type, icon, title, detail=""):
    """Append entry to file. Called by bot subprocess on every event."""
    entry = {
        "nick": nick, "type": fb_type, "icon": icon,
        "title": title, "detail": detail,
        "ts": time.time(),
    }
    try:
        entries = _load_feedback()
        entries.append(entry)
        entries = entries[-_MAX_ENTRIES:]  # cap to prevent unbounded growth
        _save_feedback(entries)
    except Exception as e:
        print(f"[SONG FEEDBACK] Failed to write: {e}")
    print(f"[SONG FEEDBACK] {fb_type}: {title}")

def get_and_clear_feedback():
    """Return fresh entries (<5s old). Drop only expired ones.
    Called by Flask process on every overlay poll."""
    now = time.time()
    entries = _load_feedback()
    if not entries:
        return []
    fresh = [e for e in entries if now - e.get("ts", 0) < _FEEDBACK_TTL]
    if len(fresh) != len(entries):
        _save_feedback(fresh)
    return fresh
```

### API: Include feedback in song overlay data

```python
# routes/stats.py — in get_song_overlay_data()
import spotify_handler as sh
# ... existing code ...
return jsonify({
    "now_playing": now_playing,
    "spotify_playing": playback.get("item"),
    "is_playing": playback.get("is_playing", False),
    "progress_ms": playback.get("progress_ms", 0),
    "upcoming": upcoming,
    "queue_length": len(upcoming),
    "feedback": sh.get_and_clear_feedback(),  # ← ADD THIS
})
```

### Frontend: Toast Queue Logic

```javascript
// State
let toastQueue = [];
let toastPlaying = false;
let toastSeenTs = new Set();  // deduplicate by timestamp

function handleSong(data) {
  // ... existing song logic ...

  // Process feedback toasts
  if (data.feedback && data.feedback.length > 0) {
    data.feedback.forEach(fb => {
      const key = fb.ts.toFixed(3);  // dedup key
      if (toastSeenTs.has(key)) return;
      toastSeenTs.add(key);
      toastQueue.push(fb);
    });
    // Cap seen set to prevent memory leak
    if (toastSeenTs.size > 200) {
      const arr = [...toastSeenTs];
      toastSeenTs = new Set(arr.slice(-100));
    }
    processToastQueue();
  }
}

function processToastQueue() {
  if (toastPlaying || toastQueue.length === 0) return;
  toastPlaying = true;

  const fb = toastQueue.shift();
  const container = document.getElementById('song-toast-container');

  // Create toast element
  const toast = document.createElement('div');
  toast.className = 'song-toast song-toast-' + (fb.type || 'success');
  toast.innerHTML =
    '<div class="song-toast-icon">' + esc(fb.icon || '✓') + '</div>' +
    '<div class="song-toast-text">' +
      '<div class="song-toast-title">' + esc(fb.title) + '</div>' +
      (fb.detail ? '<div class="song-toast-detail">' + esc(fb.detail) + '</div>' : '') +
    '</div>';

  container.appendChild(toast);

  // Entrance animation (trigger reflow for restart)
  void toast.offsetWidth;
  toast.classList.add('song-toast-in');

  // Adaptive display time: speed up when queue is backing up
  const displayMs = toastQueue.length >= 3 ? 2500 : 3500;
  const gapMs = 200;

  setTimeout(() => {
    toast.classList.remove('song-toast-in');
    toast.classList.add('song-toast-out');
    setTimeout(() => {
      toast.remove();
      toastPlaying = false;
      processToastQueue();  // next in queue
    }, 300);  // fade-out duration
  }, displayMs);
}
```

### CSS

```css
/* Toast container — sits ABOVE the song card */
.song-toast-container {
  position: absolute;
  bottom: calc(100% + 8px);  /* 8px gap above song card */
  right: 0;
  width: 340px;              /* match song card width */
  pointer-events: none;
  z-index: 20;
}

/* Individual toast */
.song-toast {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  width: 100%;
  background: rgba(11,13,20,0.92);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 10px;
  padding: 10px 12px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.3);
  opacity: 0;
  transform: translateX(30px);
  transition: opacity 0.3s ease, transform 0.3s cubic-bezier(0.34,1.56,0.64,1);
  position: absolute;
  bottom: 0;
  right: 0;
}

.song-toast-in {
  opacity: 1;
  transform: translateX(0);
}

.song-toast-out {
  opacity: 0;
  transform: translateX(20px);
  transition: opacity 0.3s ease, transform 0.2s ease;
}

/* Type colors — left accent border */
.song-toast-success { border-left: 3px solid #1DB954; }
.song-toast-error   { border-left: 3px solid #ef4444; }
.song-toast-denied  { border-left: 3px solid #f59e0b; }

.song-toast-icon {
  font-size: 16px;
  flex-shrink: 0;
  margin-top: 1px;
}
.song-toast-success .song-toast-icon { color: #1DB954; }
.song-toast-error   .song-toast-icon { color: #ef4444; }
.song-toast-denied  .song-toast-icon { color: #f59e0b; }

.song-toast-text { flex: 1; min-width: 0; }

.song-toast-title {
  font-family: var(--font-heading);
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.3;
}

.song-toast-detail {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
  line-height: 1.3;
}
```

### HTML (inside the song overlay block)

```html
<div class="song-overlay-wrap">
  <div class="song-toast-container" id="song-toast-container"></div>
  <div class="song-card" id="song-card" style="display:none;">
    <!-- existing now-playing + up-next sections -->
  </div>
</div>
```

## Sim Works, Real Events Don't (Cross-Process Boundary)

If the bot runs as a subprocess (Flask spawns it via `subprocess.Popen` on `/api/bot/start` on `app.py`), the file-based pattern above is **required**. The in-memory `deque` version appears to work in sim but **silently fails for real events** because each subprocess has its own copy of module-level state.

### Why

```
Flask process                          Bot process (minecraftDiamond.py)
   ├── _feedback_queue (deque A)         ├── _feedback_queue (deque B)
   ├── /api/spotify/simulate/play  ────► │   ← on_comment "!play" fires
   │     └─ sh.push_feedback()           │     └─ sh.push_feedback()
   │          └─ deque A.append()        │          └─ deque B.append()  ← wrong process
   │                                     │
   ▼                                     │
/overlay/song poll                       │
   └─ deque A (gets sim entries)         │   └─ deque B (gets real events, but Flask never sees it)
```

Each `import` of `spotify_handler` gets its own module-level state. Sim endpoints and the overlay poll run in Flask; the `on_comment` handler runs in the bot subprocess. They share file paths but not Python objects.

### Symptoms

- ✅ Dashboard "Simulate `!play`" → toast appears in overlay
- ❌ Real viewer types `!play` → song queues, but no toast appears
- Bot process console shows `print()` from `push_song_feedback()` (the bot's queue IS getting entries — but it's the wrong one)

### Diagnostic

```bash
# In the bot's process, look for "[SONG FEEDBACK]" prints when a real event fires.
# If you see them, the bot is appending correctly — Flask just never sees it.

# In Flask's process, hit the overlay poll endpoint directly:
curl http://localhost:5000/api/stats/song
# Look at the "feedback" key — will be [] even when the bot just pushed one
```

### Fix: Use the file-based pattern (above)

The file-based pattern fixes this with zero changes to `minecraftDiamond.py`, `routes/`, or the frontend. Only `push_song_feedback()` and `get_and_clear_feedback()` need to change in `spotify_handler.py`.

### Verification

```bash
# 1. Start the exe
# 2. From a SEPARATE process, write to the file (simulating the bot):
echo '[{"nick":"test","type":"success","icon":"[OK]","title":"@test queued Test","ts":'$(date +%s)'}]' > release/song_feedback.json

# 3. Hit the overlay poll endpoint:
curl http://localhost:5000/api/stats/song | python -m json.tool
# If you see the entry under "feedback", the bridge works.
```

**Path gotcha during verification:** when running as frozen exe, `BASE_DIR = os.path.dirname(sys.executable)` = the `release/` directory. The file lives at `release/song_feedback.json`, NOT the project root. If you're testing from a separate process (e.g. a separate python script), the paths differ:
- Separate process: `D:\Ikhito\Code\TikTokMCIntegrator\release\song_feedback.json`
- Windows: `D:\Ikhito\Code\TikTokMCIntegrator\release\song_feedback.json`

Write to whichever path your test process can see; the exe will read whatever its own `BASE_DIR` resolves to.

## Message Format Rules

**Every toast MUST include the user who triggered the command.** No anonymous feedback.

| Command | Type | Icon | Title | Detail (hint) |
|---------|------|------|-------|---------------|
| `!play` success | success | ✓ | `@user queued Song — Artist` | `Use !pull to remove your request` |
| `!skip` success | success | ⏭ | `@user skipped the track` | — |
| `!pull` success | success | ↩ | `@user pulled Song — Artist` | `Request removed` |
| `!play` no results | error | ✗ | `@user — no results for "query"` | — |
| `!play` queue full | error | ✗ | `Queue is full, try again later` | — |
| `!play` denied | denied | ⊘ | `@user — level too low to request songs` | — |
| `!skip` denied | denied | ⊘ | `@user — level too low to skip` | — |
| `!skip` cooldown | denied | ⊘ | `Skip on cooldown, try again in a few seconds` | — |
| `!pull` nothing | denied | ⊘ | `@user — no pending request to pull` | — |

Detail line is optional — omit when there's no actionable hint to show.

## Queue Behavior

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Max queue depth | 6 | Drop oldest if overflow — prevents backlog explosion |
| Display time (normal) | 3.5s | Enough to read 2 lines comfortably |
| Display time (backlog ≥3) | 2.5s | Catch up faster when commands pile up |
| Gap between toasts | 200ms | Brief pause feels intentional, not glitchy |
| Fade-out duration | 300ms | Quick exit, doesn't linger |
| Dedup window | seen ts set (capped 200) | Prevents same toast showing twice from poll timing |

## Pitfalls

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| Stacking multiple toasts | Cluttered, unreadable in corner | ONE at a time, queue the rest |
| No dedup by timestamp | Same toast appears 2-3 times from polling | Track seen timestamps in a Set |
| No adaptive display time | 5 queued commands = 17.5s delay | Speed up to 2.5s when backlog ≥3 |
| `position: absolute` without relative parent | Toasts float off-screen | Wrap in `song-overlay-wrap` which has `position: fixed` |
| Missing `void toast.offsetWidth` before adding class | Entrance animation doesn't trigger (browser batches class changes) | Force reflow between append and class add |
| Forgetting to reset `toastPlaying` on error | Queue permanently stuck | Always reset in the setTimeout callback, use try/catch |

## Debug Simulation

When building the toast system, add simulate endpoints so you can test the full flow without TikTok live:

```python
# routes/spotify.py
@spotify_bp.route("/simulate/play", methods=["POST"])
def simulate_play():
    nick = request.json.get("nick", "testuser")
    query = request.json.get("query", "never gonna give you up")
    results = sh.search_track(query, limit=1)
    if not results:
        push_song_feedback(nick, "error", "✗", f"@{nick} — no results for \"{query}\"")
        return jsonify({"status": "no_results"})
    track = results[0]
    result = sh.add_to_queue(track, nick)
    if "error" in result:
        push_song_feedback(nick, "error", "✗", f"Queue error: {result['error']}")
        return jsonify(result), 400
    pos = result.get("position", 0) + 1
    push_song_feedback(nick, "success", "✓",
        f"@{nick} queued {track['name']} — {track['artists']}",
        "Use !pull to remove your request")
    return jsonify({"status": "queued", "track": track["name"]})

@spotify_bp.route("/simulate/skip", methods=["POST"])
def simulate_skip():
    nick = request.json.get("nick", "testuser")
    result = sh.skip_track()
    if "error" in result:
        push_song_feedback(nick, "error", "✗", f"Skip error: {result['error']}")
        return jsonify(result), 400
    push_song_feedback(nick, "success", "⏭", f"@{nick} skipped the track")
    return jsonify({"status": "skipped"})

@spotify_bp.route("/simulate/pull", methods=["POST"])
def simulate_pull():
    nick = request.json.get("nick", "testuser")
    queue = sh.load_queue()
    for i, q in enumerate(queue):
        if q.get("requested_by", "").lower() == nick and q.get("status") in ("queued", "pushed"):
            track_name = q.get("track_name", "")
            artist = q.get("artist", "")
            sh.remove_from_queue(i, nick)
            push_song_feedback(nick, "success", "↩",
                f"@{nick} pulled {track_name} — {artist}",
                "Request removed")
            return jsonify({"status": "pulled", "track": track_name})
    push_song_feedback(nick, "denied", "⊘", f"@{nick} — no pending request to pull")
    return jsonify({"status": "nothing_to_pull"})
```

Dashboard UI: add a "Simulate Commands" section with username input + 3 buttons (play/skip/pull). Each calls the simulate endpoint. The overlay toast should appear immediately since the simulate endpoint pushes to the feedback queue.
