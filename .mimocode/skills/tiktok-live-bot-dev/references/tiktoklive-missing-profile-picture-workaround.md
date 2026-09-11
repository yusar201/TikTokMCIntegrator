# TikTokLive Missing Profile Picture Workaround

## Problem
A TikTokLive library bug can cause user profile-picture fields to be empty on some events even when `nickname` / `unique_id` are still present. If the bot writes that empty value into overlay state, profile pictures disappear and overlays fall back to initials.

## Backend pattern
Use a persistent last-known avatar cache, not only overlay-side image error handling.

Recommended helpers:

- `resolve_avatar_url(user, nick, unique_id)`
  - extract current avatar from known image fields (`avatar_thumb`, `avatar_medium`, `avatar_large`, camelCase variants, etc.)
  - if found, write to `data/avatar_cache.json`
  - if missing, return the cached value
- cache keys:
  - `uid:<unique_id>` preferred
  - `nick:<lowercase nick>` fallback

Seed the cache from all user-carrying events:

- `GiftEvent`
- `CommentEvent`
- `FollowEvent`
- SuperFan/Barrage wrapper events

For accumulated state like top-gifter ranking, store `unique_id` as well as `nick`, so later events can reliably match the cached avatar.

## API pattern
If an overlay endpoint reads persistent state that may already contain empty `avatar_url`, enrich on read from `avatar_cache.json` before returning JSON.

## Frontend pattern
Continue using the overlay avatar state machine:

- set fallback initial first
- hide image before setting `src`
- `onload` shows image and hides fallback
- `onerror` hides image and shows fallback

If the overlay skips rerendering unchanged totals, include `avatar_url` in the render hash. Otherwise a repaired avatar may not paint until the user's score changes.

## Limitation
This only preserves avatars the bot has seen at least once. If TikTokLive never provides a picture for a user, initials remain the correct fallback.
