# Packed-alpha gift animation performance budget

## Trigger
Use this when an animated TikTok gift asset stores RGB in the left half of a video and alpha/matte data in the right half, requiring browser canvas composition.

## Why it can melt a streaming PC
`getImageData()` and `putImageData()` force CPU-side pixel work. A compositor that does all of the following on every `requestAnimationFrame` runs independently in each browser context:

1. draw RGB and alpha halves to work canvases;
2. read the full alpha work canvas;
3. scan every pixel to find content bounds;
4. read output and alpha frames;
5. rebuild output alpha per pixel;
6. write output pixels back.

That means OBS Browser Source **and** a dashboard WebView2 preview can both consume major CPU even if the Python EXE looks quiet in Task Manager. Profile child browser processes by parent/command line; do not judge only `TikTokMCIntegrator.exe`.

## Production-safe budget
- Use a `requestAnimationFrame` scheduler but skip work until a fixed frame interval has elapsed. `50 ms` = 20 FPS and is a practical ceiling for a small corner overlay.
- Learn the alpha-mask crop throughout the **first complete video loop**, growing a padded union bbox. Detect the first loop by tracking `video.currentTime` and freezing when it wraps backward. Then reuse the crop forever; do not scan on later loops.
- Do **not** replace first-loop learning with an arbitrary early-frame cap. Validation against 40 production assets showed 27 revealed content beyond their first 10 composed frames, often far above the early bbox.
- At the fixed 20 FPS render rate, sample each budgeted frame during that first loop. Sparse 100–200 ms sampling can miss brief one-frame extents; per-budgeted-frame sampling matched the full padded extent across the cached set while remaining finite.
- Use contain scaling (`Math.min(outW/cropW, outH/cropH)`) to guarantee the complete union bbox fits the output canvas. Center horizontally and bottom-anchor vertically. Cover scaling (`Math.max`) intentionally overflows one axis and can crop tall gifts at the top.
- Dashboard URLs carrying `?preview=true` must use the static gift icon and never initialize the packed-alpha video/canvas path. OBS sources without `preview=true` retain animation.
- Keep output canvases small and keep existing asset failure fallback to the static icon.
- The template has multiple packed-alpha consumers. Whenever changing shared constants or crop logic, inspect and regression-test Top Gift/Top Showcase **and** Gift Goal; otherwise one renderer may keep a removed constant or the old scale policy.

## Asset-level crop verification
Use the actual cached production MP4 set, not a synthetic rectangle. For each packed asset:
1. Probe width/height and split the right-half matte.
2. Decode at the production 20 FPS rate and downscale to the compositor work width.
3. Apply the same alpha threshold and per-frame padding as the browser.
4. Compare the union bbox from the candidate learning schedule with the padded union across all decoded frames.
5. Require zero missed extent on every side before shipping. Also verify the generated JavaScript parses, the relevant Flask routes return 200, and the deployed template hashes match source.

## Measurement protocol
1. Capture a baseline over 15 seconds with `Get-Process` CPU deltas for:
   - app-owned `msedgewebview2.exe` processes (`--webview-exe-name=TikTokMCIntegrator.exe`),
   - `obs-browser-page.exe`,
   - OBS, Minecraft client, and Mohist separately.
2. Do not conflate process CPU percentages with total-system causality. The app EXE can be low while its WebView2 child is high.
3. After a frontend deploy/restart, repeat the same 15-second sample. Ensure app WebView2 is near idle when not actively rendering a preview.
4. Then test a real high-value animated gift in OBS. Build/runtime verification is not proof of visual animation quality; confirm it still renders correctly.

## Deployment
This changes only `templates/overlay.html`: use `./deploy.sh --fast`, but only after TikTokMCIntegrator is closed. Do not interrupt an active stream without explicit approval; a locked WebView2 process can cause a half-deploy.
