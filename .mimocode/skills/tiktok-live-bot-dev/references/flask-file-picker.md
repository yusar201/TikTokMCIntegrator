# Flask Native File Picker Pattern

**Use `<input type="file">` for file selection. Do NOT build custom file browser modals.**

The user explicitly rejected a custom modal browser. They want the standard Windows file picker dialog that every website uses. This is simpler AND better UX.

## Backend (app.py)

Add an upload endpoint. Files get saved to a known directory on the server:

```python
@app.route("/api/upload-sound", methods=["POST"])
def upload_sound():
    """Upload a sound file, save to sounds/ dir, return path."""
    if 'file' not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    # Save to sounds/ directory (create if needed)
    sounds_dir = os.path.join(BASE_DIR, "sounds")
    os.makedirs(sounds_dir, exist_ok=True)

    from werkzeug.utils import secure_filename
    filename = secure_filename(file.filename)
    filepath = os.path.join(sounds_dir, filename)
    file.save(filepath)

    return jsonify({"path": filepath, "filename": filename})
```

## Frontend (script.js)

### Add Browse Button

```javascript
if (type === 'sound') {
    fieldsHtml = `
      <div style="display:flex;gap:4px;align-items:center;">
        <input type="text" class="action-field action-file" 
               placeholder="File path (auto-filled after upload)" 
               value="${escHtml(data?.file || '')}" style="flex:1;">
        <button class="btn btn-sm btn-secondary" type="button" 
                style="padding:4px 10px;white-space:nowrap;" 
                onclick="pickSoundFile(this)">Browse</button>
      </div>
      <input type="text" class="action-field action-url" placeholder="OR URL" value="${escHtml(data?.url || '')}">
      <input type="number" class="action-field action-volume" placeholder="Volume (0-1)" 
             min="0" max="1" step="0.1" value="${data?.volume ?? 0.8}" style="width:80px;">`;
}
```

### File Picker Function

```javascript
function pickSoundFile(btn) {
  const input = btn.parentElement.querySelector('.action-file');
  const fileInput = document.createElement('input');
  fileInput.type = 'file';
  fileInput.accept = '.mp3,.wav,.ogg,.flac,.aac,.m4a,.wma,audio/*';
  fileInput.style.display = 'none';

  fileInput.onchange = async () => {
    const file = fileInput.files[0];
    if (!file) return;

    btn.textContent = 'Uploading...';
    btn.disabled = true;

    const formData = new FormData();
    formData.append('file', file);

    try {
      const resp = await fetch('/api/upload-sound', { method: 'POST', body: formData });
      const data = await resp.json();
      if (data.error) {
        alert('Upload failed: ' + data.error);
      } else {
        input.value = data.path;
      }
    } catch (e) {
      alert('Upload error: ' + e.message);
    }

    btn.textContent = 'Browse';
    btn.disabled = false;
    fileInput.remove();
  };

  document.body.appendChild(fileInput);
  fileInput.click();
}
```

## Why Native Over Custom

| Approach | Pros | Cons |
|----------|------|------|
| Native `<input type="file">` | Standard UX, works everywhere, OS file dialog | Files upload to server |
| Custom modal browser | Full filesystem control | Over-engineered, confusing, limited |

**User preference: Always use native file picker.** They said: "i want a real windows file browser"

## Customization

- Change `fileInput.accept` for different file types
- Change the upload directory (`sounds/`) as needed
- Add file size validation in the backend if needed
