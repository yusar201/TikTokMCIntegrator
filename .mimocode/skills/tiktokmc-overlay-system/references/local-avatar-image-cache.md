# Local Avatar Image Cache for TikTok Profile Pictures

## Problem
TikTok avatar/profile-picture URLs are signed CDN URLs. Storing the URL in `avatar_cache.json` or `gifter_ranking.json` is not enough: the overlay can load the image at first, then later the URL expires/rotates or returns 403, so podium/chat/follow avatars fall back to initials.

This is distinct from TikTokLive omitting the avatar field. The existing backend `avatar_cache.json` workaround prevents blank event fields from overwriting a known URL, but it does **not** make that URL durable.

## Correct local-cache architecture
Download the image while the signed TikTok URL is still valid and serve the downloaded file from the Flask app:

```text
TikTok avatar URL
→ download image immediately with browser-like headers
→ save under assets/avatar_cache/
→ store a same-origin URL like /avatar_cache/<unique_id>_<hash>.webp
→ overlay uses the local URL forever
```

Use `paths.ASSETS_DIR` / `paths.assets(...)`; never hardcode release paths. In frozen release this resolves to `release/assets/avatar_cache/`; in dev it resolves to `assets/avatar_cache/`.

## Implementation pattern
Add a helper module such as `avatar_cache.py`:

- `cache_avatar_image(source_url, nick, unique_id) -> local_url | ""`
  - Reject empty/data/local URLs.
  - Generate filename from stable user identifier + SHA1 of source URL.
  - Download using headers:
    - `User-Agent: Mozilla/5.0 ... Chrome ...`
    - `Referer: https://www.tiktok.com/`
    - `Accept: image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8`
  - Cap size (e.g. 2 MB).
  - Validate image magic bytes: WEBP, JPEG, PNG, GIF.
  - Write atomically via temp file + `os.replace`.
  - Return `/avatar_cache/<filename>`.
- `is_local_avatar_url(url)` returns true for `/avatar_cache/`.
- `local_avatar_path_from_url(local_url)` safely maps route URL to file path for missing-file checks.

Add Flask route in `app.py`:

```python
@app.route('/avatar_cache/<path:fname>')
def serve_avatar_cache(fname):
    if '..' in fname or fname.startswith('/') or fname.startswith('\\\\'):
        abort(404)
    avatar_dir = os.path.join(paths.ASSETS_DIR, 'avatar_cache')
    full_path = os.path.abspath(os.path.join(avatar_dir, fname))
    root = os.path.abspath(avatar_dir)
    if os.path.commonpath([root, full_path]) != root or not os.path.exists(full_path):
        abort(404)
    return send_from_directory(avatar_dir, os.path.basename(fname), as_attachment=False, max_age=86400)
```

Wire avatar resolution:

```python
raw_url = _raw_avatar_url(user)
if raw_url:
    local_url = cache_avatar_image(raw_url, nick, unique_id)
    stable_url = local_url or raw_url  # temporary fallback while signed URL still works
    store stable_url in avatar_cache.json / gifter_ranking.json
```

For existing release data, backfill in `/api/stats/topgifter`: when an entry has an external TikTok avatar URL, call `cache_avatar_image(...)`, replace `entry['avatar_url']` with `/avatar_cache/...`, and persist both `gifter_ranking.json` and `avatar_cache.json`. If a local URL exists but the file is missing, retry from `source_url` if available.

## Frontend still needs fallback
Keep the overlay-side avatar state machine:

- Set fallback initial first.
- Start `<img>` hidden.
- `onload`: show image, hide fallback.
- `onerror`: hide image, show fallback.
- Include `avatar_url` in topgifter render hash so repaired URLs repaint even if coin total does not change.

Local caching makes URLs durable, but it cannot recover avatars the bot never saw or URLs that already expired before first download.

## Verification recipe

```bash
python3 -m py_compile avatar_cache.py minecraft_main.py routes/stats.py app.py
python3 - <<'PY'
import json, os, shutil
from pathlib import Path
root = Path('D:\Ikhito\Code\TikTokMCIntegrator')
data_dir = root / 'data'
data_dir.mkdir(exist_ok=True)
rank = data_dir / 'gifter_ranking.json'
av = data_dir / 'avatar_cache.json'
rank_bak = rank.with_suffix('.json.testbak')
av_bak = av.with_suffix('.json.testbak')
rank_existed = rank.exists(); av_existed = av.exists()
if rank_existed: shutil.copy2(rank, rank_bak)
if av_existed: shutil.copy2(av, av_bak)
try:
    src = json.loads((root/'release/data/gifter_ranking.json').read_text())[:3]
    rank.write_text(json.dumps(src, ensure_ascii=False, indent=2), encoding='utf-8')
    av.write_text('{}', encoding='utf-8')
    import app as a
    c = a.app.test_client()
    data = c.get('/api/stats/topgifter').get_json()
    assert data and all(x.get('avatar_url','').startswith('/avatar_cache/') for x in data)
    for item in data:
        r = c.get(item['avatar_url'])
        assert r.status_code == 200 and len(r.data) > 20
finally:
    if rank_existed: shutil.move(rank_bak, rank)
    else: rank.unlink(missing_ok=True)
    if av_existed: shutil.move(av_bak, av)
    else: av.unlink(missing_ok=True)
PY
```

After deploy, restart `release/TikTokMCIntegrator.exe` so the new route and resolver are active.
