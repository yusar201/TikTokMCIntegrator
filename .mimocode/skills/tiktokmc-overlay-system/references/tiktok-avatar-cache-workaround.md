# TikTokLive Avatar Cache Workaround for Overlays

## Problem
TikTokLive can intermittently omit or blank user profile-picture fields on live events while the user identity/nickname is still present. For overlays such as `topgifter`, this makes the avatar disappear and fall back to initials even though the bot previously saw the user's profile picture.

This is distinct from normal CDN URL expiry. The overlay-side `onload`/`onerror` state machine prevents broken image icons, but it cannot restore an avatar when the backend sends an empty `avatar_url`.

## Durable workaround
Add a backend-side persistent avatar cache:

- Store last-known avatar URLs in `data/avatar_cache.json`.
- Key primarily by stable TikTok unique ID, fallback by normalized nickname:
  - `uid:<unique_id>`
  - `nick:<lowercase nick>`
- Seed the cache from every event that has user data, not just gifts:
  - chat/comment events
  - follow events
  - gift events
  - superfan/barrage events
- When an event has no avatar URL, resolve `avatar_url` from the cache before writing overlay state/logs.
- For ranking/podium state, persist `unique_id` alongside `nick`, `avatar_url`, totals, etc.
- API endpoints that serve overlay state can also enrich missing `avatar_url` from the cache before returning JSON.

## Top gifter overlay-specific notes
`topgifter` ranking is long-lived during a stream, so it is especially sensitive to one blank gift event overwriting an existing avatar.

Backend pattern:

```python
avatar_url = resolve_avatar_url(user, nick, unique_id)
update_gifter_ranking(nick, avatar_url, total_coin, unique_id)
```

Inside `update_gifter_ranking`, only replace `entry["avatar_url"]` when a non-empty resolved URL exists. If the current event has no URL, pull from `avatar_cache.json` instead of writing `""`.

Endpoint enrichment pattern:

```python
for entry in data:
    if entry.get("avatar_url"):
        continue
    entry["avatar_url"] = lookup_avatar_cache(entry.get("nick"), entry.get("unique_id"))
```

Frontend pattern:

The podium already uses the `avatar-display-pattern.md` onload/onerror state machine. Also include avatar URL in the render hash so the UI updates when the backend later enriches the same coin total:

```javascript
const hash = JSON.stringify(data.map(g => `${g.nick}:${g.total_coins}:${g.avatar_url || ''}`));
```

If the hash only includes `nick:total_coins`, an avatar repaired by the cache may not render until the user's coin count changes again.

## Verification
- `python -m py_compile minecraft_main.py routes/stats.py`
- Jinja render check for `overlay.html` and `overlay_demo.html` with `overlay_type='topgifter'`
- API fixture check: ranking entry with empty `avatar_url` + cache entry should return enriched avatar URL from `/api/stats/topgifter`.

## Limitations
This cannot recover avatars the bot has never seen. It prevents regressions after at least one event provided a usable profile picture URL.
