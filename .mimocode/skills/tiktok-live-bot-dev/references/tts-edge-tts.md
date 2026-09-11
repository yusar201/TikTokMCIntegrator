# TTS via edge-tts (. prefix trigger)

TikFinity-style text-to-speech using the `.` prefix on chat messages. No overlay — audio plays through desktop audio and is captured by OBS.

## Architecture

```
Viewer types .hello world
  → minecraftDiamond.py on_comment detects . prefix
  → strips . → sends "hello world" to http://127.0.0.1:5000/api/tts/speak
  → Flask generates mp3 via edge_tts (Microsoft neural voice)
  → pygame mixer plays audio through desktop audio
  → OBS captures desktop audio → stream hears it
```

Chat message still goes to Minecraft normally (the `.` prefix is detected after `log_and_send()`).

## Detection in on_comment

Must be placed AFTER `log_and_send()` (chat goes to MC first), BEFORE song commands:

```python
# ── TTS Trigger (. prefix) ──────────────────────────────────────
comment_stripped = comment.strip()
if comment_stripped.startswith("."):
    tts_text = comment_stripped[1:].strip()  # strip . and whitespace
    if tts_text:  # skip "..." or ". " (no actual text)
        try:
            import urllib.request
            data = json.dumps({"text": tts_text, "nick": nick}).encode("utf-8")
            req = urllib.request.Request(
                "http://127.0.0.1:5000/api/tts/speak",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as tts_err:
            print(f"[TTS] Failed to send TTS request: {tts_err}")
```

`urllib.request` is stdlib — no extra dependency for minecraftDiamond.py.

## Flask Endpoint

```python
import threading, asyncio
import edge_tts, pygame, time
from flask import request, jsonify

_tts_last_at = 0  # global cooldown tracker

@app.route("/api/tts/speak", methods=["POST"])
def tts_speak():
    global _tts_last_at

    data = request.get_json()
    text = data.get("text", "").strip() if data else ""
    if not text:
        return jsonify({"status": "error", "message": "No text provided"}), 400
    if len(text) > 200:
        return jsonify({"status": "error", "message": "Text too long (max 200 chars)"}), 400

    # Cooldown: 2s between TTS messages
    now = time.time()
    if now - _tts_last_at < 2:
        return jsonify({"status": "skipped", "message": "TTS cooldown"}), 200
    _tts_last_at = now

    def _play_tts():
        try:
            tts_dir = os.path.join(BASE_DIR, "tts")
            os.makedirs(tts_dir, exist_ok=True)
            out_file = os.path.join(tts_dir, f"tts_{int(time.time())}.mp3")

            async def _gen():
                communicate = edge_tts.Communicate(text, "en-US-AriaNeural")
                await communicate.save(out_file)

            asyncio.run(_gen())

            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)

            sound = pygame.mixer.Sound(out_file)
            sound.play()
        except Exception as e:
            print(f"[TTS] Error: {e}")

    threading.Thread(target=_play_tts, daemon=True).start()
    return jsonify({"status": "ok"})
```

## PyInstaller bundling

Add `edge_tts` to hiddenimports in the spec:

```python
hiddenimports=['spotipy', 'spotipy.oauth2', 'spotipy.client', 'spotify_handler', 'edge_tts'],
```

## Voice configuration

Default: `en-US-AriaNeural` (Microsoft's neutral female voice).

Unused by Ikhito currently — all hardcoded. If customization is needed:
- 400+ voices available via `edge_tts.list_voices()` (async, returns by locale)
- Can add `voice` field to config or as a query parameter
- Common option: `en-US-GuyNeural` (male), `en-GB-SoniaNeural` (British female)

## Pitfalls

- **PyInstaller ignores dynamically-imported modules.** edge_tts must be in `hiddenimports` or the built exe won't include it → `ModuleNotFoundError: No module named 'edge_tts'` at runtime.
- **`asyncio.run()` from a Flask thread:** Flask runs synchronously, so `asyncio.run()` is safe here (no running event loop). The TTS generation happens in a daemon thread so the HTTP response returns immediately.
- **pygame.mixer must be initialized.** The main process may or may not have pygame.mixer initialized (depends on whether sound actions have been triggered). Always check `get_init()` before using.
- **TTS files accumulate.** `tts/` directory fills up with mp3 files. Not critical (small files, ~5-20KB each) but clean periodically if needed.
- **`. ` (period-space) or `...` triggers no TTS.** The `[1:].strip()` check ensures the text after the period is non-empty — dots-only messages are ignored.
