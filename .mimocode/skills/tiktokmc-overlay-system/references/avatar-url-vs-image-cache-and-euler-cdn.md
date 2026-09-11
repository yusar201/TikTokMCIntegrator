# TikTok avatar URLs vs real image caching / Euler CDN

## Problem class
TikTok profile-picture URLs from TikTokLive are signed CDN URLs. They can render correctly for a while, then later fail in OBS/browser overlays and fall back to initials (e.g. topgifter podium shows `C` instead of the profile picture).

There are TWO distinct failure modes:

1. **TikTokLive omits/returns blank avatar fields** on an event.
   - Existing fix: `data/avatar_cache.json` stores the last-known avatar URL keyed by `uid:<unique_id>` and `nick:<nick>`.
   - This only repairs missing fields in later events.

2. **The stored TikTok avatar URL expires or is blocked later**.
   - `avatar_cache.json` does NOT fix this if it stores the original TikTok URL.
   - URLs often include `x-expires=...` and remain fragile even when cached in JSON.
   - Symptom: image originally loads, then after time/poll/reload the overlay falls back to the initial.

## Key lesson
Do not call the current `avatar_cache.json` a “local image cache” unless it actually downloads and serves image files. A JSON cache of TikTok URLs is only a URL cache.

## Evidence pattern to check
Inspect release runtime state, not just source dev state:

- `release/data/gifter_ranking.json`
- `release/data/avatar_cache.json`

If `avatar_url` values still point at `p16-common-sign.tiktokcdn...` / `p19-common-sign.tiktokcdn...`, the overlay is still using expiring TikTok URLs directly.

## Real local cache design
A self-contained local fix must download the avatar while the TikTok URL is still valid and store a same-origin Flask-served URL:

```text
TikTok event avatar URL
→ download image immediately/off-event-loop
→ save under assets/avatar_cache/<stable-key>.webp
→ store overlay URL like /assets/avatar_cache/<stable-key>.webp
→ topgifter/chat/follow APIs return that local URL
```

Recommended cache key:

- Prefer `unique_id` / stable TikTok ID.
- Fallback to normalized nickname only when no stable ID exists.
- Avoid unsafe filename chars; hash source URL or sanitize the key.

Store metadata, not only a string:

```json
{
  "avatar_url": "/assets/avatar_cache/dhhorus.webp",
  "source_url": "https://p19-common-sign.tiktokcdn-us.com/...",
  "updated_at": 1783500234
}
```

Keep overlay `onload`/`onerror` fallback state machine anyway. Local downloads can still fail, files can be missing, or first-seen avatars can be unavailable.

## Euler CDN alternative
Euler Stream Image CDN is directly relevant. It mirrors TikTok signed image URLs to a stable CDN URL.

Known docs facts from session:

- Default endpoint shape: `https://<cdnId>.assets.cdn.eulerstream.com`
- Public access ON allows OBS/browser to read cached images without a key.
- Public uploads OFF means only the account API key can populate/cache new images.
- A shortened/stable CDN URL cannot fetch an image it has never seen; the full signed TikTok URL must be passed at least once.
- Community limits: 50 req/min per account, 20 req/min per IP.

Use Euler CDN when Khito wants less local code and accepts the external dependency. Use real local caching when he wants no third-party runtime dependency, no CDN rate limit, and same-origin OBS image loads.

## Debugging checklist
1. Check the API response from `/api/stats/topgifter` or runtime JSON files.
2. If URLs are TikTok CDN URLs, local image caching has NOT been implemented.
3. Test current top URLs with real GET, not HEAD only; some TikTok CDNs reject HEAD with 405 while GET works.
4. Parse `x-expires` from the query to confirm the URL is signed/expiring.
5. If current URLs load now but older cache entries return 403/expired, the root cause is URL expiry, not overlay CSS.

## Implementation caution
Do not block TikTok event handling/RCON on image downloads. Use a short-timeout background worker or queue, then patch the cache/ranking entry when the local/CDN URL is ready. Include avatar URL in the topgifter render hash so repaired images repaint even if coin totals did not change.
