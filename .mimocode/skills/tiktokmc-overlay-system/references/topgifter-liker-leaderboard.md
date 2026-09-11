# Top Gifter & Top Liker Rotating Leaderboard Recipe

Session: 2026-08-05. Replaced the top-3 Stardew podium (`references/podium-overlay-recipe.md`, now historical) with a compact list-style leaderboard that rotates **Top Gifters (coins)** and **Top Likers (likes)** every ~5 seconds in ONE OBS source. Route kept as `/overlay/topgifter` so OBS sources needed no change. Khito crops to top 3 in OBS, but the API serves top 10 for both boards.

## Frontend design (`.lb-wrap`, both overlay.html AND overlay_demo.html)

- Container: `position:fixed; bottom:20px; left:50%; transform:translateX(-50%); width:380px;` pixel font, hidden (`opacity:0`) when both boards empty. Dashboard preview-centering selector must target `.lb-wrap` (old `.podium-wrap` selector breaks preview centering).
- Header: two-tab pill (`.lb-tab#lb-tab-gifters` 🪙 TOP GIFTERS / `.lb-tab#lb-tab-likers` ❤️ TOP LIKERS); `.active` tab gets gold-block background.
- Rows: rank number (gold/diamond/bronze tint for 1-3 via `:nth-child`), 38px square pixel avatar (border color matches rank tier), pink `#ff9ecb` name (rank 1 gold `#ffd76a`), right-aligned score with icon. Row entrance: staggered `lbRowIn` slide (delay `i * 0.04s`). Rank-1 avatar gets the pixel-crown SVG (`crownBob` keyframes MUST include `translateX(-50%)` in every keyframe or the crown drifts off-center — the demo template re-declares them).
- Avatar robustness: same onload/onerror fallback-initial state machine as everywhere else (see `avatar-display-pattern.md`).

## JS contract

- `handleTopGifter(data)` now accepts the NEW shape `{gifters: [...], likers: [...]}` (old shape was a bare array). Each entry: gifters `{nick, avatar_url, total_coins}`, likers `{nick, avatar_url, total_likes}`. Dedup via `JSON.stringify([gifters, likers])` hash; a `setInterval(…, 5000)` flips `lbMode` and re-renders. If only one board has entries, rotation sticks to that board so the overlay never blanks.
- Score key is mode-dependent: `total_coins` vs `total_likes`.

## Avatar parity (2026-08-15 — liker initials bug)

The liker board MUST resolve avatars through the SAME `resolve_avatar_url(user, nick, uid)` path the gifter/chat/follow handlers use. The bug: `on_like` fed `getattr(user, "avatar", "")` — a field TikTokLive's like-event payload does NOT populate — so every liker row had an empty `avatar_url` and the overlay fell back to initials even when a usable avatar existed for that user. Gifters were fine because `on_gift` calls `resolve_avatar_url`, which extracts `avatar_thumb`/`avatarThumb`/`avatar_medium`/etc. (via `_raw_avatar_url`), seeds `data/avatar_cache.json`, and falls back to last-known via `_cached_avatar_url`.

Fix pattern (mirror in `minecraft_main.py::on_like`):
```python
uid = getattr(user, "unique_id", "") or ""
avatar_url = resolve_avatar_url(user, nick, uid)   # NOT getattr(user, "avatar", "")
stream_ranking.update(LIKER_RANKING_FILE, nick, avatar_url, batch, unique_id=uid, ...)
```
Also short-circuit `_cache_avatar_url` so an unchanged URL skips the `safe_json_write` — likes fire in bursts and would otherwise rewrite `avatar_cache.json` on every tap.

## Amount-visibility toggles (2026-08-15)

Khito wanted a show/hide switch for coin (gifter) and like (liker) amounts, both default **hidden**. Correct placement is the DASHBOARD card (`templates/index.html`), NOT inside `overlay.html` — a checkbox rendered in the overlay shows up on-stream. The dashboard checkbox POSTs to `/api/stats/overlay/settings`; `/api/stats/topgifter` folds `show_gift_amounts` / `show_like_amounts` into its payload, and the overlay applies them via `lbShowAmounts` on its existing poll. `handleTopGifter` must include the flags in its hash so a toggle repaints even when board data is unchanged. When hidden, render `scoreHtml` as `''` and keep `.lb-row .lb-score:empty { min-width:0; padding-left:0; }` so rows stay aligned.

## PITFALL — keyed reconciliation, never full rebuild (2026-08-05 flicker fix)

First version wiped `list.innerHTML` and rebuilt ALL rows on every data change; every row had `animation: lbRowIn` → under active likes/gifts the whole list re-played its slide-in entrance every poll = constant flicker. **Do not rebuild rows on score-only updates.** `lbRender()` must:
- Patch existing rows IN PLACE by index (rank text, `.lb-name`, `.lb-score` innerHTML, avatar via `lbPatchAvatar`) — same DOM node, so no CSS animation can restart.
- Animate ONLY genuinely new rows: entrance class is `.lb-row.lb-new` (NOT base `.lb-row`); new rows get `lb-new` + staggered delay.
- Full rebuild (`innerHTML=''`) only on board rotation (`modeChanged` via `lbRenderedMode`) — that entrance animation is desired there.
- Avatars: `lbPatchAvatar` keeps a `data-avatar-key` (the avatar_url) on the avatar wrapper; identity unchanged → only refresh the fallback initial letter, never re-create the img element (TikTok URLs churn).
- Verified with 20 rapid score-only updates: `list.children[0]` identity stable, scores updated, no animation restart; new entrant animates once at its slot.

## Backend pipeline (stream_ranking.py)

- Lightweight per-stream JSON stores, NOT the long-term SQLite points DB: `data/gifter_ranking.json` + `data/liker_ranking.json`. Throttled flush (likes are high-frequency — never write per event), top-10 trim on read, manual-reset token file handling with `ack_reset_token()` so a stale token can't wipe a fresh live after restart/reconnect, and `_check_reset_token()` throttled so the token file isn't read on every like.
- `minecraft_main.py`: `update_gifter_ranking(nick, avatar_url, total_coins, unique_id="")` delegates to stream_ranking (signature preserved); `on_like` accumulates per-user like batches from `LikeEvent` (TikTok only sends batch counts, no persistent totals — must accumulate); fresh live (`on_connect`, non-reconnect) resets BOTH boards; reconnect reloads via `init_from_disk()`; live-end flushes.
- `routes/stats.py`: `GET /api/stats/topgifter` returns `{gifters: [...10], likers: [...10]}` with shared avatar enrichment; `POST /api/stats/topgifter/reset` clears BOTH boards (note blueprint prefix → full URL `/api/stats/topgifter/reset`).

## Dashboard touchpoints

- `templates/index.html`: card title "Top Gifter & Liker Leaderboard", hint "Rotating top-10 gifters (coins) / likers (likes), resets each new live", OBS size hint **400 x 260 (crop to top 3 rows)** (was 500 x 420 podium). Bump `style.css?v=` / `script.js?v=` cache-busters.
- `static/script.js`: `resetTopGifter()` confirm/toast wording covers both boards.
- `static/style.css`: `#preview-topgifter` height override was 600px for the old podium; shrunk to **320px** for the compact leaderboard (verified 2026-08-05).
- **Shipped/verified 2026-08-05**: tests/test_stream_ranking.py (12 cases), full suite 392 passed, deploy.sh --full, preview screenshots on temp port 5050 (gifters + likers rotation confirmed), cleanup done.

## Tooling pitfall — large template replacements

A single `patch` tool call replacing the whole podium CSS+markup+JS block timed out (~8K token tool-call limit). Working pattern: do the replacement in Python via `execute_code` — `src.index(start_marker)` / `src.index(end_marker)` with `assert` on expected sentinels inside the excised span, splice in the new block, write back. One call per block (CSS / markup / JS separately), mirrored second pass for `overlay_demo.html`. Always assert boundary sentinels before splicing so a shifted marker fails loudly instead of corrupting the template.
