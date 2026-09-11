# Gift Animation Downloader toggle + packaging pitfalls (2026-06-22)

## Symptom

User saw live console output even though the dashboard appeared to show Gift Animation Downloader as OFF:

```text
[!] Gift asset download error for Naughty Chicken: No module named 'gift_assets'
[+] Gift: Claudia ... gave Naughty Chicken (id=11179) 1 times. Total Coin: 299
```

## Root cause

Two issues stacked:

1. **UI toggle was not wired into config load/save.** The checkbox existed in `templates/index.html`, but `static/script.js` did not populate or save `Settings.GiftAssetDownloader`. The page could visually look OFF while `release/config/config.yml` still contained:

```yaml
Settings:
  GiftAssetDownloader: true
```

2. **Dynamic import path was stale after folderized layout.** The source tree moved downloader code under:

```text
assets/gift_assets/downloader.py
```

but the bot still tried:

```python
from gift_assets.downloader import download_gift_asset
```

Correct import:

```python
from assets.gift_assets.downloader import download_gift_asset
```

Because it is dynamic and only executed for 100+ coin gifts when enabled, `py_compile` can pass while release runtime still fails unless PyInstaller includes it.

## Required fix pattern

### Dashboard JS

In `populateSettings()`:

```js
const gadChk = document.getElementById('gift-asset-downloader');
const gadLbl = document.getElementById('gift-asset-downloader-label');
if (gadChk) {
  gadChk.checked = !!currentConfig.Settings.GiftAssetDownloader;
  if (gadLbl) gadLbl.textContent = gadChk.checked ? 'Enabled' : 'Disabled';
  if (!gadChk._wired) {
    gadChk.addEventListener('change', () => {
      if (gadLbl) gadLbl.textContent = gadChk.checked ? 'Enabled' : 'Disabled';
    });
    gadChk._wired = true;
  }
}
```

In `saveSettings()`:

```js
const gadChk = document.getElementById('gift-asset-downloader');
currentConfig.Settings.GiftAssetDownloader = !!(gadChk && gadChk.checked);
```

### Bot import

```python
from assets.gift_assets.downloader import download_gift_asset
```

### PyInstaller spec

Add hidden imports because downloader is imported dynamically:

```python
'assets.gift_assets.downloader', 'assets.gift_assets.manifest'
```

## Multi-streamer / alternate GiftEvent asset URLs (2026-07-04)

**Symptom:** The Top Gift overlay still shows a static gift image while connected to a different streamer, even for gifts that should have animation.

**Root causes to check first:**

1. `release/config/config.yml` may still have `Settings.GiftAssetDownloader: false`. The release config is the one the live exe reads, so source config alone is not enough.
2. TikTok does not always put the playable animation at `event.asset.resource_url.url_list[0]`. Depending on gift/room/proto variant, candidates can be under:
   - `event.asset.resource_url.url_list`
   - `event.asset.video_resource_list[*].video_url.url_list`
   - `event.asset.resource_bytevc1_url.url_list` (fallback; may be less browser-friendly)
   - `event.asset_bundle.assets[*]` using the same fields above

**Backend fix pattern:** extract a de-duped ordered list of candidate URLs, prefer normal resource/video URLs before bytevc1, then let the background downloader try each URL until one succeeds. Do not block the TikTok event loop. Keep `asset_pending` on the gift log entry and patch `asset_url` into `gift_log.json` when the worker succeeds.

**User-facing behavior:** first sighting of a 100+ coin gift may still show static briefly while the animation downloads; the same gift should animate immediately once cached in `assets/gift_assets/manifest.json`.

## Verification

- Check actual release config, not the visual checkbox alone:

```bash
python - <<'PY'
import yaml
p='release/config/config.yml'
c=yaml.safe_load(open(p,encoding='utf-8')) or {}
print(c.get('Settings',{}).get('GiftAssetDownloader'))
PY
```

- Run:

```bash
C:\Python313\python.exe -m py_compile minecraft_main.py app.py main.py assets/gift_assets/downloader.py assets/gift_assets/manifest.py
node --check static/script.js
python - <<'PY'
from assets.gift_assets.downloader import download_gift_asset
print('import ok', callable(download_gift_asset))
PY
```

- If changing the URL resolver, add/keep a tiny fixture-style probe for `_gift_asset_source_urls()` with mock `resource_url`, `video_resource_list`, `resource_bytevc1_url`, and `asset_bundle.assets` objects. It should return a de-duped ordered URL list.

## TikTok ZIP bundle pitfall (2026-07-04)

TikTok gift animation resource URLs often end in `.zip` / `.x-zip-compressed` and contain:

```text
output.mp4
config.json
```

Do **not** save that ZIP payload as `gift_<id>.mp4`. Browser `<video>` will fail to decode it; the top-gift overlay then retries the same bad `asset_url` on every poll and visually glitches/flickers every couple seconds. Correct downloader behavior:

1. Detect ZIP by magic bytes (`PK\x03\x04`), not only URL extension.
2. Extract the best playable member (`output.mp4` / `.webm` / `.gif`, JSON only as last resort).
3. Save the extracted payload as `assets/gift_assets/gift_<id>.<ext>`.
4. Update manifest `local` to the runtime Windows path when repairing release cache, and set `local_url` with a cache-busting query when replacing a bad file currently referenced by `gift_log.json`.
5. In the overlay, keep a per-session failed-asset blacklist so one unsupported/corrupt asset falls back to the static icon once instead of retry-flickering every poll.

Emergency live repair for already-cached ZIP-as-MP4 files: extract `output.mp4` from every `release/assets/gift_assets/gift_*.mp4` whose first bytes are `PK`, overwrite the file with the extracted MP4, update `release/assets/gift_assets/manifest.json`, and update active `release/data/gift_log.json` `asset_url` to `/gift_assets/gift_<id>.mp4?v=<timestamp>` so OBS reloads the corrected file.

## Live-stream caution

If a user reports the downloader is off but logs show downloads, immediately check `release/config/config.yml`. If it is `true`, set it false directly as a safe immediate mitigation, then deploy the UI wiring fix later when the app can be closed.

Do **not** assume dashboard toggle state reflects saved config unless the load/save wiring is verified.