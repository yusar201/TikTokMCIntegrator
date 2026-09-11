# Audio Preview Pattern for Dashboard

When adding audio preview to the TikTokMCIntegrator dashboard (browse + play/stop), use this pattern.

## Backend (app.py)

Add a Flask endpoint to serve audio files from the `sounds/` directory with path traversal protection:

```python
@app.route("/api/preview-sound", methods=["GET"])
def preview_sound():
    """Serve a sound file for preview playback."""
    filepath = request.args.get("path", "")
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404

    # Security: only allow serving from the sounds/ directory
    sounds_dir = os.path.join(BASE_DIR, "sounds")
    real_path = os.path.realpath(filepath)
    real_sounds = os.path.realpath(sounds_dir)
    if not real_path.startswith(real_sounds):
        return jsonify({"error": "Access denied"}), 403

    return send_file(filepath, mimetype="audio/mpeg")
```

`send_file` is already imported in the Flask imports.

## Frontend (script.js)

### Button HTML (in `appendActionRowToContainer`)

Add next to the Browse button:
```html
<button class="btn btn-sm btn-ghost preview-sound-btn" type="button" 
        style="padding:4px 8px;" onclick="previewSound(this)" title="Preview sound">
  <i class="fa-solid fa-play"></i>
</button>
```

### JavaScript Functions

Global state for single-preview-at-a-time:
```javascript
let _previewAudio = null;
let _previewBtn = null;
```

Play/stop toggle. Works with both local files (via `/api/preview-sound`) and direct URLs:
```javascript
function previewSound(btn) {
  if (_previewAudio && _previewBtn === btn) { stopPreview(); return; }
  if (_previewAudio) stopPreview();

  const row = btn.closest('.action-row');
  const filePath = row.querySelector('.action-file')?.value?.trim() || '';
  const fileUrl = row.querySelector('.action-url')?.value?.trim() || '';
  const volume = parseFloat(row.querySelector('.action-volume')?.value) || 0.8;

  let audioSrc = '';
  if (fileUrl && (fileUrl.startsWith('http://') || fileUrl.startsWith('https://'))) {
    audioSrc = fileUrl;
  } else if (filePath) {
    audioSrc = '/api/preview-sound?path=' + encodeURIComponent(filePath);
  } else {
    showToast('No sound file selected!', 'error');
    return;
  }

  _previewAudio = new Audio(audioSrc);
  _previewAudio.volume = Math.min(1, Math.max(0, volume));
  _previewBtn = btn;
  _previewAudio.onended = () => stopPreview();
  _previewAudio.onerror = () => { showToast('Failed to load audio file', 'error'); stopPreview(); };
  _previewAudio.play().then(() => {
    btn.innerHTML = '<i class="fa-solid fa-stop"></i>';
    btn.style.color = '#f44336';
  }).catch(e => { showToast('Playback error: ' + e.message, 'error'); stopPreview(); });
}

function stopPreview() {
  if (_previewAudio) { _previewAudio.pause(); _previewAudio.currentTime = 0; _previewAudio.src = ''; _previewAudio = null; }
  if (_previewBtn) { _previewBtn.innerHTML = '<i class="fa-solid fa-play"></i>'; _previewBtn.style.color = ''; _previewBtn = null; }
}
```

## Security Notes

- Path traversal protection uses `os.path.realpath()` to resolve symlinks before checking the prefix
- Only files under `sounds/` are served; arbitrary file access is blocked
- URLs (http/https) are played directly in the browser, not proxied through the server

## Pitfalls

- **Update BOTH copies:** `static/script.js` AND `release/.../static/script.js`
- **Volume slider:** Preview respects the volume input field value, so the user hears it at the configured level
- **Single preview:** Only one sound can preview at a time. Starting a new preview auto-stops the previous one.
