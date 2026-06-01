# Song Command Feedback Toast Overlay — Implementation Plan

**Project:** TikTokMCIntegrator
**Root:** `/mnt/d/Ikhito/Code/TikTokMCIntegrator/`
**Goal:** Add slide-in toast notifications to the song overlay showing feedback for `!play`, `!skip`, `!pull` commands, plus debug simulation endpoints.

**Architecture:** In-memory feedback queue (deque) in `spotify_handler.py`. Commands push feedback entries. The `/api/stats/song` endpoint returns and clears the queue. The overlay JS polls every 1s, renders toasts one at a time sequentially.

---

## Overview of Changes

| # | File | Type | What |
|---|------|------|------|
| 1 | `spotify_handler.py` | Modify | Add feedback deque + push/get functions |
| 2 | `routes/stats.py` | Modify | Include feedback in song API response |
| 3 | `static/style.css` | Modify | Toast CSS (container, animations) |
| 4 | `templates/overlay.html` | Modify | Toast queue JS in handleSong() |
| 5 | `routes/spotify.py` | Modify | Add 3 simulate endpoints |
| 6 | `templates/index.html` | Modify | Add Simulate Commands UI section |
| 7 | `static/script.js` | Modify | Add simulate JS functions |
| 8 | `minecraftDiamond.py` | Modify | Wire real commands to push feedback |

---

## Task 1: Add Feedback Queue to `spotify_handler.py`

**File:** `spotify_handler.py` (in project root)

**What:** Add an in-memory deque and two functions at module level. Place them AFTER the existing imports and BEFORE the existing functions (around line 50-60, after the `_write_lock` and `QUEUE_FILE` definitions).

### Step 1.1: Add the deque (after existing module-level globals, around line 40-50)

Find this pattern in the file:
```python
QUEUE_FILE = os.path.join(BASE_DIR, "song_queue.json")
```

Add these lines RIGHT AFTER the `QUEUE_FILE` / `_write_lock` block:

```python
# ── Song Feedback Queue (for overlay toast notifications) ──────────────
from collections import deque
import time as _feedback_time

_song_feedback_queue = deque(maxlen=20)
```

### Step 1.2: Add push and get functions

Add these two functions after the feedback deque. Place them before any existing function definitions (or right after the `save_queue` / `load_queue` functions if that's easier):

```python
def push_song_feedback(nick, feedback_type, icon, title, detail=""):
    """Push a feedback entry for the overlay toast.
    
    Args:
        nick: Username who triggered the command (e.g. "koolguy99")
        feedback_type: "success", "error", or "denied"
        icon: Emoji icon (e.g. "✓", "⏭", "↩", "✗", "⊘")
        title: Main message line (e.g. "@koolguy99 queued Song — Artist")
        detail: Subtle hint line (e.g. "Use !pull to remove your request")
    """
    _song_feedback_queue.append({
        "nick": nick,
        "type": feedback_type,
        "icon": icon,
        "title": title,
        "detail": detail,
        "timestamp": _feedback_time.time(),
    })
    print(f"[SONG FEEDBACK] {feedback_type}: {title}")


def get_and_clear_feedback():
    """Return all pending feedback entries and clear the queue."""
    entries = list(_song_feedback_queue)
    _song_feedback_queue.clear()
    return entries
```

---

## Task 2: Add Feedback to Song API Response

**File:** `routes/stats.py`

**What:** Add the `feedback` field to the `/api/stats/song` endpoint response.

### Step 2.1: Import the feedback function

At the top of `routes/stats.py`, inside the `get_song_overlay_data()` function (around line 116), the file already does `import spotify_handler as sh`. No new import needed.

### Step 2.2: Add feedback to the response

Find the `return jsonify({...})` block at the end of `get_song_overlay_data()` (around line 151-158):

```python
    return jsonify({
        "now_playing": now_playing,
        "spotify_playing": playback.get("item"),
        "is_playing": playback.get("is_playing", False),
        "progress_ms": playback.get("progress_ms", 0),
        "upcoming": upcoming,
        "queue_length": len(upcoming),
    })
```

Replace it with:

```python
    return jsonify({
        "now_playing": now_playing,
        "spotify_playing": playback.get("item"),
        "is_playing": playback.get("is_playing", False),
        "progress_ms": playback.get("progress_ms", 0),
        "upcoming": upcoming,
        "queue_length": len(upcoming),
        "feedback": sh.get_and_clear_feedback(),
    })
```

---

## Task 3: Add Toast CSS to `static/style.css`

**File:** `static/style.css`

**What:** Append toast styles at the END of the file (after the existing song overlay styles). The toast sits above the song card in the bottom-right corner.

### Step 3.1: Append this CSS at the very end of `static/style.css`

```css
/* ============ SONG COMMAND FEEDBACK TOAST ============ */
.song-feedback-wrap {
  position: fixed;
  bottom: calc(16px + 8px);  /* 8px gap above song card */
  right: 16px;
  width: 340px;
  display: flex;
  flex-direction: column-reverse;
  gap: 6px;
  pointer-events: none;
  z-index: 15;
  /* Reserve space so toast doesn't block content below */
}

.song-feedback-toast {
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  background: rgba(11,13,20,0.94);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 10px;
  padding: 10px 14px;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  box-shadow: 0 4px 24px rgba(0,0,0,0.5);
  animation: toastSlideIn 0.4s cubic-bezier(0.34,1.56,0.64,1) forwards;
  transform-origin: bottom right;
  overflow: hidden;
  position: relative;
}

.song-feedback-toast::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  border-radius: 10px 0 0 10px;
}

/* Type accents */
.song-feedback-toast.type-success::before { background: #1DB954; }
.song-feedback-toast.type-error::before   { background: #ef4444; }
.song-feedback-toast.type-denied::before  { background: #f59e0b; }

.song-feedback-toast.toast-exit {
  animation: toastSlideOut 0.3s ease-in forwards;
}

@keyframes toastSlideIn {
  0%   { opacity: 0; transform: translateX(60px) scale(0.9); }
  100% { opacity: 1; transform: translateX(0) scale(1); }
}

@keyframes toastSlideOut {
  0%   { opacity: 1; transform: translateX(0) scale(1); }
  100% { opacity: 0; transform: translateX(40px) scale(0.95); }
}

.song-feedback-icon {
  font-size: 16px;
  line-height: 1;
  flex-shrink: 0;
  margin-top: 1px;
}
.song-feedback-toast.type-success .song-feedback-icon { color: #1DB954; }
.song-feedback-toast.type-error   .song-feedback-icon { color: #ef4444; }
.song-feedback-toast.type-denied  .song-feedback-icon { color: #f59e0b; }

.song-feedback-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.song-feedback-title {
  font-family: var(--font-heading, 'Outfit', sans-serif);
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.song-feedback-detail {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-muted, #64748b);
  line-height: 1.3;
}
```

---

## Task 4: Add Toast Queue JS to `templates/overlay.html`

**File:** `templates/overlay.html`

**What:** Add a toast container div and the toast queue logic inside the song overlay section.

### Step 4.1: Add toast container HTML

Find the song overlay div structure (around line 482-507). Find this block:

```html
{% elif overlay_type == 'song' %}
<div class="song-overlay-wrap">
  <div class="song-card" id="song-card" style="display:none;">
```

ADD this toast container RIGHT BEFORE `<div class="song-overlay-wrap">`:

```html
{% elif overlay_type == 'song' %}
<div class="song-feedback-wrap" id="song-feedback-wrap"></div>
<div class="song-overlay-wrap">
  <div class="song-card" id="song-card" style="display:none;">
```

### Step 4.2: Add toast queue JS

In the `<script>` section, find the existing song-related variables. There should be variables like `songIsPlaying`, `lastSyncedTrackId`, etc. near the top of the script block. Right after those variables, add:

```javascript
// ============ SONG FEEDBACK TOAST QUEUE ============
const feedbackQueue = [];
let feedbackShowing = false;
const FEEDBACK_BASE_DURATION = 3500;  // 3.5s per toast
const FEEDBACK_FAST_DURATION = 2500;  // 2.5s when 3+ queued
const FEEDBACK_GAP = 200;             // 200ms between toasts
const FEEDBACK_MAX_QUEUE = 6;

function processFeedbackQueue() {
  if (feedbackShowing || feedbackQueue.length === 0) return;
  feedbackShowing = true;

  const item = feedbackQueue.shift();
  const wrap = document.getElementById('song-feedback-wrap');
  if (!wrap) { feedbackShowing = false; return; }

  // Create toast element
  const toast = document.createElement('div');
  toast.className = `song-feedback-toast type-${item.type}`;
  toast.innerHTML = `
    <span class="song-feedback-icon">${item.icon}</span>
    <div class="song-feedback-body">
      <div class="song-feedback-title">${esc(item.title)}</div>
      ${item.detail ? `<div class="song-feedback-detail">${esc(item.detail)}</div>` : ''}
    </div>
  `;
  wrap.appendChild(toast);

  // Duration: shorten if queue is backing up
  const duration = feedbackQueue.length >= 3 ? FEEDBACK_FAST_DURATION : FEEDBACK_BASE_DURATION;

  setTimeout(() => {
    toast.classList.add('toast-exit');
    setTimeout(() => {
      toast.remove();
      feedbackShowing = false;
      // Process next in queue after gap
      setTimeout(processFeedbackQueue, FEEDBACK_GAP);
    }, 300); // match CSS exit animation duration
  }, duration);
}

function enqueueFeedback(entries) {
  if (!entries || entries.length === 0) return;
  entries.forEach(item => {
    if (feedbackQueue.length >= FEEDBACK_MAX_QUEUE) {
      feedbackQueue.shift(); // drop oldest
    }
    feedbackQueue.push(item);
  });
  processFeedbackQueue();
}
```

### Step 4.3: Wire feedback into handleSong()

Find the `handleSong(data)` function (around line 1117). At the VERY BEGINNING of the function, right after the opening `{`, add:

```javascript
function handleSong(data) {
  // Process feedback toasts FIRST (runs every poll cycle)
  if (data.feedback && data.feedback.length > 0) {
    enqueueFeedback(data.feedback);
  }

  // ... rest of existing handleSong code ...
```

This should be the FIRST lines inside handleSong, before `const card = document.getElementById('song-card');`.

---

## Task 5: Add Simulate Endpoints to `routes/spotify.py`

**File:** `routes/spotify.py`

**What:** Add 3 POST endpoints for debugging: simulate play, skip, pull.

### Step 5.1: Add simulate endpoints

At the END of the file (after the last existing route), add:

```python
# ── Simulate Commands (for overlay debug) ──────────────────────────────

@spotify_bp.route("/simulate/play", methods=["POST"])
def simulate_play():
    """Simulate a !play command. Searches Spotify, queues first result, pushes feedback."""
    data = request.json or {}
    nick = data.get("nick", "testuser")
    query = data.get("query", "")
    if not query:
        sh.push_song_feedback(nick, "error", "✗", f"@{nick} — no search query provided")
        return jsonify({"error": "Query required"}), 400

    # Search
    results = sh.search_track(query, limit=5)
    if isinstance(results, dict) and "error" in results:
        sh.push_song_feedback(nick, "error", "✗", f"@{nick} — search failed: {results['error']}")
        return jsonify(results), 400
    if not results:
        sh.push_song_feedback(nick, "error", "✗", f'@{nick} — no results for "{query}"')
        return jsonify({"error": "No results", "feedback_pushed": True})

    track = results[0]

    # Queue
    result = sh.add_to_queue(track, nick)
    if "error" in result:
        if "duplicate" in result.get("error", "").lower() or "already" in result.get("error", "").lower():
            sh.push_song_feedback(nick, "denied", "⊘", f"@{nick} — {result['error']}")
        else:
            sh.push_song_feedback(nick, "error", "✗", f"@{nick} — {result['error']}")
        return jsonify(result), 400

    pos = result.get("position", 0) + 1
    sh.push_song_feedback(
        nick, "success", "✓",
        f"@{nick} queued {track['name']} \u2014 {track['artists']}",
        f"Position #{pos} \u2022 Use !pull to remove your request"
    )

    # Try direct push if nothing playing
    try:
        token = sh.get_valid_token()
        if token:
            playback = sh.get_current_playback()
            if not playback.get("is_playing") and not playback.get("item"):
                sh.queue_track(track["uri"])
                queue = sh.load_queue()
                for i, q in enumerate(queue):
                    if q.get("spotify_uri") == track.get("uri") and q.get("status") in ("queued", "pushed"):
                        q["status"] = "playing"
                        break
                sh.save_queue(queue)
    except Exception as e:
        print(f"[SIMULATE] Direct push error (non-fatal): {e}")

    return jsonify({"success": True, "track": track, "position": pos, "feedback_pushed": True})


@spotify_bp.route("/simulate/skip", methods=["POST"])
def simulate_skip():
    """Simulate a !skip command. Skips current track, pushes feedback."""
    data = request.json or {}
    nick = data.get("nick", "testuser")

    result = sh.skip_track()
    if isinstance(result, dict) and "error" in result:
        sh.push_song_feedback(nick, "error", "✗", f"@{nick} — skip failed: {result['error']}")
        return jsonify(result), 400

    sh.push_song_feedback(nick, "success", "⏭", f"@{nick} skipped the track")
    return jsonify({"success": True, "feedback_pushed": True})


@spotify_bp.route("/simulate/pull", methods=["POST"])
def simulate_pull():
    """Simulate a !pull command. Removes user's latest queued song, pushes feedback."""
    data = request.json or {}
    nick = data.get("nick", "testuser")

    queue = sh.load_queue()
    removed = False
    removed_track = ""
    for i, q in enumerate(queue):
        if q.get("requested_by", "").lower() == nick.lower() and q.get("status") in ("queued", "pushed"):
            removed_track = f"{q.get('track_name', 'Unknown')} \u2014 {q.get('artist', 'Unknown')}"
            sh.remove_from_queue(i, nick)
            removed = True
            break

    if removed:
        sh.push_song_feedback(
            nick, "success", "↩",
            f"@{nick} pulled {removed_track}",
            "Request removed from queue"
        )
        return jsonify({"success": True, "removed": removed_track, "feedback_pushed": True})
    else:
        sh.push_song_feedback(
            nick, "denied", "⊘",
            f"@{nick} — no pending request to pull"
        )
        return jsonify({"success": False, "message": "No pending request", "feedback_pushed": True})
```

---

## Task 6: Add Simulate Commands UI to Dashboard

**File:** `templates/index.html`

**What:** Add a "Simulate Commands" section in the Song panel, right after the existing Test Search section.

### Step 6.1: Find the Test Search section

Search for this HTML in `templates/index.html`:

```html
<div id="song-test-results" class="song-list compact"></div>
```

Right AFTER that closing `</div>`, and BEFORE the closing `</section>` tag, add:

```html
            <!-- Simulate Commands -->
            <section class="song-card" style="margin-top:16px;">
              <div class="song-card-header compact">
                <div>
                  <h3><i class="fa-solid fa-vial"></i> Simulate Commands</h3>
                  <p>Test overlay feedback toasts. Username appears in every toast.</p>
                </div>
              </div>
              <div style="display:flex;flex-direction:column;gap:10px;">
                <div style="display:flex;gap:8px;align-items:center;">
                  <label style="font-size:12px;color:var(--text-muted);white-space:nowrap;">Username:</label>
                  <input type="text" id="sim-nick" value="testuser" placeholder="testuser" class="form-input" style="flex:1;">
                </div>
                <div style="display:flex;gap:8px;align-items:center;">
                  <label style="font-size:12px;color:var(--text-muted);white-space:nowrap;">Song query:</label>
                  <input type="text" id="sim-query" value="never gonna give you up" placeholder="song name..." class="form-input" style="flex:1;">
                </div>
                <div style="display:flex;gap:8px;flex-wrap:wrap;">
                  <button class="btn btn-primary" onclick="simPlay()" style="flex:1;">
                    <i class="fa-solid fa-play"></i> Sim !play
                  </button>
                  <button class="btn btn-warning" onclick="simSkip()" style="flex:1;">
                    <i class="fa-solid fa-forward-step"></i> Sim !skip
                  </button>
                  <button class="btn btn-danger" onclick="simPull()" style="flex:1;">
                    <i class="fa-solid fa-arrow-rotate-left"></i> Sim !pull
                  </button>
                </div>
                <div id="sim-status" style="font-size:11px;color:var(--text-muted);min-height:16px;"></div>
              </div>
            </section>
```

**Note:** If the section tag wrapping the test search doesn't have a clear closing point, just add the simulate section as a new sibling `<section>` right after the test search section closes.

---

## Task 7: Add Simulate JS Functions to `static/script.js`

**File:** `static/script.js`

**What:** Add the 3 simulate button handlers at the end of the file (before the closing or after the last function).

### Step 7.1: Append at end of `static/script.js`

```javascript
// ==========================================
// SIMULATE COMMANDS (Debug)
// ==========================================
function _simStatus(msg, type) {
  const el = document.getElementById('sim-status');
  if (!el) return;
  const colors = { success: '#1DB954', error: '#ef4444', info: '#64748b' };
  el.style.color = colors[type] || colors.info;
  el.textContent = msg;
  clearTimeout(el._timer);
  el._timer = setTimeout(() => { el.textContent = ''; }, 4000);
}

async function simPlay() {
  const nick = (document.getElementById('sim-nick')?.value || 'testuser').trim();
  const query = (document.getElementById('sim-query')?.value || '').trim();
  if (!query) { _simStatus('Enter a song query', 'error'); return; }
  _simStatus('Simulating !play...', 'info');
  try {
    const res = await fetch('/api/spotify/simulate/play', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nick, query })
    });
    const data = await res.json();
    if (data.feedback_pushed) {
      _simStatus(`✓ Feedback pushed for @${nick} — check overlay!`, 'success');
      fetchSongQueue();
    } else {
      _simStatus(data.error || 'Failed', 'error');
    }
  } catch(e) {
    _simStatus('Error: ' + e.message, 'error');
  }
}

async function simSkip() {
  const nick = (document.getElementById('sim-nick')?.value || 'testuser').trim();
  _simStatus('Simulating !skip...', 'info');
  try {
    const res = await fetch('/api/spotify/simulate/skip', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nick })
    });
    const data = await res.json();
    if (data.feedback_pushed) {
      _simStatus(`✓ Skip feedback pushed for @${nick} — check overlay!`, 'success');
    } else {
      _simStatus(data.error || 'Failed', 'error');
    }
  } catch(e) {
    _simStatus('Error: ' + e.message, 'error');
  }
}

async function simPull() {
  const nick = (document.getElementById('sim-nick')?.value || 'testuser').trim();
  _simStatus('Simulating !pull...', 'info');
  try {
    const res = await fetch('/api/spotify/simulate/pull', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nick })
    });
    const data = await res.json();
    if (data.feedback_pushed) {
      _simStatus(`✓ Pull feedback pushed for @${nick} — check overlay!`, 'success');
      fetchSongQueue();
    } else {
      _simStatus(data.error || 'No pending request', 'error');
    }
  } catch(e) {
    _simStatus('Error: ' + e.message, 'error');
  }
}
```

---

## Task 8: Wire Real Commands to Push Feedback

**File:** `minecraftDiamond.py`

**What:** Replace the `send_minecraft_command("tell ...")` calls in the song command handler with `sh.push_song_feedback(...)` calls.

### Step 8.1: !play success (around line 996-1000)

Find:
```python
                    # Confirm to viewer
                    pos = result.get("position", 0) + 1
                    await send_minecraft_command(
                        f"tell {MC_USERNAME} §a[Song] §f{track['name']} §7by {track['artists']} §aadded to queue (pos #{pos})"
                    )
```

Replace with:
```python
                    # Push feedback to overlay toast
                    pos = result.get("position", 0) + 1
                    sh.push_song_feedback(
                        nick, "success", "✓",
                        f"@{nick} queued {track['name']} \u2014 {track['artists']}",
                        f"Position #{pos} \u2022 Use !pull to remove your request"
                    )
```

### Step 8.2: !play no results (around line 965-967)

Find:
```python
                    if not results:
                        print(f"[SONG] No results for: {query}")
                        return
```

Replace with:
```python
                    if not results:
                        sh.push_song_feedback(nick, "error", "✗", f'@{nick} — no results for "{query}"')
                        return
```

### Step 8.3: !play permission denied (around line 956-958)

Find:
```python
                    if not sh.check_permission("play", user_info, tags, user_info["gifter_level"], user_info["member_level"]):
                        print(f"[SONG] {nick} denied permission for !play")
                        return
```

Replace with:
```python
                    if not sh.check_permission("play", user_info, tags, user_info["gifter_level"], user_info["member_level"]):
                        sh.push_song_feedback(nick, "denied", "⊘", f"@{nick} — level too low to request songs")
                        return
```

### Step 8.4: !play queue error (around line 974-978)

Find:
```python
                    if "error" in result:
                        print(f"[SONG] Queue error: {result['error']}")
                        # Send error as chat message
                        await send_minecraft_command(f"tell {MC_USERNAME} §c[Song] {result['error']}")
                        return
```

Replace with:
```python
                    if "error" in result:
                        sh.push_song_feedback(nick, "error", "✗", f"@{nick} — {result['error']}")
                        return
```

### Step 8.5: !skip success (around line 1024-1025)

Find:
```python
                    print(f"[SONG] {nick} skipped current track")
                    await send_minecraft_command(f"tell {MC_USERNAME} §e[Song] §f{nick} skipped the current track")
```

Replace with:
```python
                    sh.push_song_feedback(nick, "success", "⏭", f"@{nick} skipped the track")
```

### Step 8.6: !skip permission denied (around line 1013-1014)

Find:
```python
                    if not sh.check_permission("skip", user_info, tags, user_info["gifter_level"], user_info["member_level"]):
                        print(f"[SONG] {nick} denied permission for !skip")
                        return
```

Replace with:
```python
                    if not sh.check_permission("skip", user_info, tags, user_info["gifter_level"], user_info["member_level"]):
                        sh.push_song_feedback(nick, "denied", "⊘", f"@{nick} — level too low to skip")
                        return
```

### Step 8.7: !skip cooldown (around line 1008-1010)

Find:
```python
                    if now - _last_skip_time < SKIP_COOLDOWN:
                        print(f"[SONG] {nick} skip blocked (cooldown)")
                        return
```

Replace with:
```python
                    if now - _last_skip_time < SKIP_COOLDOWN:
                        sh.push_song_feedback(nick, "denied", "⊘", "Skip on cooldown, try again in a few seconds")
                        return
```

### Step 8.8: !pull success (around line 1039-1040)

Find:
```python
                    if removed:
                        await send_minecraft_command(f"tell {MC_USERNAME} §e[Song] §fYour request was revoked")
```

Replace with:
```python
                    if removed:
                        pulled_track = f"{q.get('track_name', 'Unknown')} \u2014 {q.get('artist', 'Unknown')}"
                        sh.push_song_feedback(
                            nick, "success", "↩",
                            f"@{nick} pulled {pulled_track}",
                            "Request removed from queue"
                        )
```

**Important:** The `q` variable from the loop may not be accessible after `break`. To fix this, save the track name BEFORE the break. Modify the revoke loop (around line 1028-1037) to capture the track info:

Find:
```python
                    for i, q in enumerate(queue):
                        if q.get("requested_by", "").lower() == uid and q.get("status") in ("queued", "pushed"):
                            sh.remove_from_queue(i, uid)
                            removed = True
                            print(f"[SONG] {nick} revoked: {q.get('track_name', '')} (status: {q.get('status')})")
                            break
```

Replace with:
```python
                    pulled_track = ""
                    for i, q in enumerate(queue):
                        if q.get("requested_by", "").lower() == uid and q.get("status") in ("queued", "pushed"):
                            pulled_track = f"{q.get('track_name', 'Unknown')} \u2014 {q.get('artist', 'Unknown')}"
                            sh.remove_from_queue(i, uid)
                            removed = True
                            print(f"[SONG] {nick} revoked: {q.get('track_name', '')} (status: {q.get('status')})")
                            break
```

### Step 8.9: !pull nothing found (around line 1041-1042)

Find:
```python
                    else:
                        await send_minecraft_command(f"tell {MC_USERNAME} §c[Song] No pending request found")
```

Replace with:
```python
                    else:
                        sh.push_song_feedback(nick, "denied", "⊘", f"@{nick} — no pending request to pull")
```

---

## Verification Steps

### After all tasks:

1. **Start the app:**
   ```bash
   cd /mnt/d/Ikhito/Code/TikTokMCIntegrator
   python app.py
   ```

2. **Open song overlay** in browser:
   ```
   http://localhost:5000/overlay/song
   ```

3. **Open dashboard** in browser:
   ```
   http://localhost:5000/
   ```
   Navigate to Song tab → scroll down to "Simulate Commands"

4. **Test !play simulation:**
   - Username: `testuser`
   - Query: `never gonna give you up`
   - Click "Sim !play"
   - Overlay should show toast: `✓ @testuser queued Never Gonna Give You Up — Rick Astley` with detail `Position #1 • Use !pull to remove your request`
   - Toast slides in from right, stays 3.5s, slides out

5. **Test !skip simulation:**
   - Click "Sim !skip"
   - Overlay should show toast: `⏭ @testuser skipped the track`

6. **Test !pull simulation:**
   - Click "Sim !pull"
   - Overlay should show toast: `↩ @testuser pulled Never Gonna Give You Up — Rick Astley` with detail `Request removed from queue`

7. **Test queue behavior:**
   - Rapid-click all 3 buttons quickly
   - Toasts should play ONE AT A TIME, sequentially
   - No overlap, smooth transitions

8. **Test error states:**
   - Sim !play with empty query → error toast
   - Sim !pull twice (second time = no pending) → denied toast

### Expected toast timeline for rapid-fire:
```
0.0s  →  ✓ @testuser queued Song A (slides in)
3.5s  →  (slides out)
3.7s  →  ⏭ @testuser skipped the track (slides in)
7.2s  →  (slides out)
7.4s  →  ↩ @testuser pulled Song A (slides in)
10.9s →  (slides out)
```

---

## Important Notes

- **OBS Browser Source:** The song overlay URL in OBS should be `http://localhost:5000/overlay/song`. After changes, refresh the OBS browser source.
- **Style.css location:** The main `static/style.css` is the one that matters. The copies in `release/` and `dist/` will be updated when you run `build.bat`.
- **No changes to build system:** All changes are in source files. Run `build.bat` to propagate to release.
- **Thread safety:** `_song_feedback_queue` uses `deque` which is thread-safe for append/popleft in CPython. The `push_song_feedback` function is called from the TikTok comment handler thread, and `get_and_clear_feedback` is called from Flask request threads. This is safe.
- **`!revoke` command name:** The actual command in config defaults to `!revoke`. The overlay feedback messages reference `!pull` as the user-facing hint. The command name itself stays configurable in `config.yaml` via `revoke_command`. If you want to rename the default from `!revoke` to `!pull`, change it in `spotify_handler.py` line 63 (`"revoke_command": "!revoke"` → `"revoke_command": "!pull"`).
