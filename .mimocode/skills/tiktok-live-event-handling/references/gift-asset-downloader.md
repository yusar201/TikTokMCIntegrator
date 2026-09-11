# Gift Asset Downloader — Working Pattern

An opt-in on-demand downloader for TikTok gift animation assets. The current folderized implementation lives at `D:\Ikhito\Code\TikTokMCIntegrator\assets\gift_assets\` and is wired into `minecraft_main.py`'s `on_gift` handler. The pattern is reusable for any "first time I see X, download it once, serve it locally" feature.

## TL;DR

- Toggle: `Settings.GiftAssetDownloader` in `config.yml` (default `false`)
- 100+ coin gifts trigger a download
- File goes to `<BASE_DIR>/assets/gift_assets/gift_<id>.<ext>` (detected from URL: mp4, webm, json, gif, default mp4)
- Manifest at `<BASE_DIR>/assets/gift_assets/manifest.json` — `{gift_id: {local, local_url, source, type, ts}}`
- Flask serves files at `/gift_assets/<path:fname>` with path-traversal protection
- Idempotent: cached gifts return the existing local URL instantly

## Why this pattern

- **First-hit download**: gift only fires the download once per gift_id. Subsequent gifts of the same type return the local URL with no network call.
- **Manifest, not DB**: small JSON file is enough for hundreds of gift types. Easy to inspect, easy to reset (just delete the file).
- **Sanity guard**: rejects downloads smaller than 256 bytes (catches 404 HTML pages and CDN error stubs).
- **Toggle-first**: opt-in only. Most users will leave it off because the animations cost disk + network. Default off keeps the existing UX unchanged.
- **Hot-reload safe**: bot reads `GIFT_ASSET_DOWNLOADER` at startup, but the toggle is on the Flask/UI side and only matters next time the bot restarts. Don't auto-restart on toggle change — just warn the user.

## Files

- `assets/gift_assets/__init__.py` — package marker
- `assets/gift_assets/manifest.py` — JSON store + `get_entry` / `set_entry` helpers
- `assets/gift_assets/downloader.py` — `download_gift_asset(gift_id, url, timeout=8)` returns local URL or None
- `app.py` — `@app.route('/gift_assets/<path:fname>')` with `send_from_directory` + path-traversal guard
- `minecraft_main.py` — `_is_gift_downloader_enabled()` live config read, hook in `on_gift`, `asset_url` added to ctx
- `static/script.js` — must both populate and save `Settings.GiftAssetDownloader` from `#gift-asset-downloader`; otherwise the toggle can visually look off while release/config.yml stays true
- `TikTokMCIntegrator.spec` — include hidden imports for dynamic downloader import: `assets.gift_assets.downloader`, `assets.gift_assets.manifest`

## Path-traversal guard (the must-have)

```python
@app.route('/gift_assets/<path:fname>')
def serve_gift_asset(fname):
    if '..' in fname.split('/') or fname.startswith(('/', '\\')):
        abort(404)
    gift_assets_dir = os.path.join(BASE_DIR, 'gift_assets')
    if not os.path.exists(os.path.join(gift_assets_dir, fname)):
        abort(404)
    return send_from_directory(gift_assets_dir, fname, as_attachment=False)
```

`send_from_directory` is safe by default, but the explicit `..` check makes the security posture obvious. Don't trust CDN URLs blindly — some redirect to attacker-controlled hosts.

## Detection heuristic (100+ coin threshold)

The `diamond_count >= 100` threshold is empirical. Below 100 = standard animated sticker, no asset to download. Above 100 = full TikTok-style animation with downloadable asset. This isn't documented anywhere — it's just the threshold the proto data starts having populated `event.asset.resource_url` for. Some gifts below 100 will still have assets, some above 100 won't. Worth tuning.

## What the URL format actually is

Empirically confirmed (live test 2026-06-05): TikTok serves MP4 **2-up format** — color on left half, alpha/luminance mask on right half. This is TikTok's standard SDK format for compositing transparent animations. The raw MP4 plays in any browser `<video>` but has a black background where alpha should be.

**Overlay handling (two approaches):**
1. **CSS crop to left half** — `object-position: left` + `width: 50%`. Simple, black background disappears on dark overlays. Not truly transparent.
2. **Canvas composite** — render to canvas, use right half as alpha mask over left half. Proper transparency over any background. More code.

The `VideoResource.video_type_name` field tells you the MIME (`video/mp4`, `video/webm`, etc.) but it's not always populated. Fallback URL sniff: `.webm` → `webm`, `.json`/`lottie` → `json`, `.gif` → `gif`, else `mp4`. Browser `<video>` plays mp4/webm. For Lottie (`.json`), you need `lottie-web` or similar.

## Known failure modes

- **CDN URL expiry**: some TikTok asset CDN URLs may have short TTLs (exact window unknown). Cache immediately on first sight — the downloader fires during `on_gift` so by the time the overlay reads it, the file is already on disk. If the download fails gracefully (timeout/404), the asset_url stays empty and the overlay falls back to text-only.
- **Bot restart + overlay state**: if the bot restarts, the manifest persists, but the Flask route needs a manual reload to pick up new files. The `<BASE_DIR>/gift_assets/` folder is read live — no reload needed.
- **Toggle is live-read, not a startup constant**: `_is_gift_downloader_enabled()` reads from `config.yml` on every gift event. Flipping the toggle in the UI takes effect immediately — no bot restart required. Verify both UI directions are wired: `populateSettings()` must set checkbox + label from `currentConfig.Settings.GiftAssetDownloader`, and `saveSettings()` must write checkbox state back before POSTing `/api/config`. A real 2026-06-22 failure showed the dashboard looking OFF while `release/config/config.yml` still had `GiftAssetDownloader: true`, causing 100+ coin gifts to attempt downloads.
- **Folderized import path**: current import is `from assets.gift_assets.downloader import download_gift_asset`. Old `from gift_assets.downloader import ...` fails in the exe with `No module named 'gift_assets'`.
- **PyInstaller bundle**: because the downloader is imported dynamically inside `on_gift`, add hidden imports in `TikTokMCIntegrator.spec`: `assets.gift_assets.downloader`, `assets.gift_assets.manifest`. Do not rely on PyInstaller's static analysis to discover the optional branch.
- **Deploy preservation**: downloaded files live under `assets/gift_assets/`, which is NOT in the swappable list (only `_internal/`, `templates/`, `static/` swap). Downloads survive deploys. Don't `rm -rf release/` — see `tiktokmc-build-deploy` skill.

## Reference: ctx variable for templates

The new `asset_url` is in `ctx` for gift event actions — same dict as `{gift_name}`, `{repeat_count}`, `{user}`, `{total_coin}`, `{mc}`, `{amount}`, `{gift_id}`. Use it in custom message templates like:

```yaml
Events:
  Gift:
    5566:
      - command: 'say {user} sent a mishka bear! Video: {asset_url}'
        type: 'minecraft'
```

The URL is empty string `""` if downloader is off or download failed.
