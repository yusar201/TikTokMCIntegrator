---
name: tiktok-live-event-handling
description: "TikTokMCIntegrator TikTokLive 7.0.0b2 event handling and upstream-release intake — compatibility audit, matched protobuf pins, dynamic event registry, frozen-EXE verification, user identification, gift/ranking events, gift-catalog union + sync + room-scope picker, Euler webcast endpoints, send-chat feasibility/session-id, and SuperFan fallback detection."
trigger: "TikTokLive event, event_registry, tiktok event handler, ranking event, leaderboard, game rank, eulerstream webcast, on_* handler, listener registration, available_gifts, gift catalog, sync gift catalog, gift picker, room scope, session id, send_room_chat, send chat"

related_skills: ["tiktok-live-bot-dev", "tiktokmc-build-deploy"]
---

# TikTokLive Event Handling — Class-Level Skill

## Architecture Overview

TikTokMCIntegrator listens to TikTok LIVE events via the pinned Python stack `TikTokLive 7.0.0b2` + `TikTokLiveProto 0.2.2`. The library:

1. **Resolves username → room_id** via `fetch_room_id_live_html.py` (scrapes `SIGI_STATE` JSON) or `fetch_room_id_api.py` (REST)
2. **Signs a WebSocket URL** via `Euler Stream` at `https://tiktok.eulerstream.com/webcast/fetch` (raw protobuf response — the WS handshake)
3. **Opens WebSocket** to `wss://webcast.tiktok.com/...` and receives `WebcastPushFrame` binary protobuf messages
4. **Parses** each frame into one of ~60 typed event classes in `TikTokLive.events.proto_events`
5. **Dispatches** to your `@client.on(EventClass)` handlers in `minecraftDiamond.py`

## Version Compatibility

Production target: **TikTokLive 7.0.0b2 + TikTokLiveProto 0.2.2**, pinned exactly in `requirements.txt`. b2 was verified as a drop-in upgrade from a1: `TikTokLiveClient.run`, constructor, `WebDefaults`, existing event imports, and custom SuperFan classes remained compatible. See `references/tiktoklive-7.0.0b2-upgrade-audit.md` for the source diff and release-intake checklist.

**`_get_all_badge_info` monkey-patch status:** upstream `ExtendedUser._get_all_badge_info` still reads v2 names (`self.badges`, `badge.badge_scene`, `log_extra`) while the v3 schema uses `badge_list`, `scene_type`, and `privilege_log_extra`. Keep the project's patch in `minecraft_main.py`; verify it in the same Windows Python environment used by PyInstaller.

**Pinning rule:** pin the top-level client and its generated schema as a matched pair (`TikTokLive==7.0.0b2`, `TikTokLiveProto==0.2.2`). Do not independently pin transitive packages such as `websockets` or `protobuf` unless a demonstrated compatibility issue requires it; let TikTokLive's own metadata constrain them. Validate the complete `requirements.txt` in a fresh venv because unrelated stale pins can make an otherwise-correct release uninstallable.

## Upstream Release Intake — Relevance Filter and Verification

When Isaac/Euler posts a multi-language or infrastructure release bundle, classify before changing anything:

1. **Select the runtime actually used:** this project is Python, so evaluate `TikTokLive` + `TikTokLiveProto`. Ignore npm/TypeScript, C#, Java/Kotlin/Maven artifacts unless the project gains a component in that runtime.
2. **Separate service changes from client changes:** Euler dashboard, Discord bot, OAuth, leaderboards, proxy-mesh internals, queue backend, and SaaS add-ons are irrelevant unless project code calls those surfaces. Sign/Gift Gallery changes matter only when the matching endpoint or response headers are consumed.
3. **Inspect package metadata and wheel contents:** confirm exact dependency pairing, license/additional terms, new event export, decoder mapping, and field names. Do not infer support from release prose alone.
4. **Diff against the installed production version:** compare public signatures/imports, custom events, monkey patches, signer defaults, schema fields, and PyInstaller-sensitive dynamic imports.
5. **TDD the integration:** add a failing requirements/registry contract test, then update pins and registry metadata. For generic dynamic actions, an `EVENT_REGISTRY` entry is enough; add a hard-coded handler only when bespoke behavior or logging is required.
6. **Exercise a constructed event:** instantiate the real event class and pass it through `build_context`. For `LinkMicBattleItemCardEvent`, verify `battle_id`, enum `msg_type`, and `award_reason` become stable strings.
7. **Validate environments:** fresh venv install + `pip check`, complete test suites, then Windows build-Python import/compile checks.
8. **Build and smoke the frozen EXE:** use `./deploy.sh --full`; launch only for verification, check `/health` and `/api/event-registry`, confirm the new entry, then stop the smoke-test process unless the user asked to leave it running.

**License intake:** inspect the license shipped in the exact wheel. The 7.0.0b2 AGPL additional permissions explicitly cover TikTok LIVE stream bots/overlays/games, but exclude prohibited hosted SaaS/API/relay use. Record the classification; do not silently assume an older MIT license still applies.

**Battle item card integration:** expose `LinkMicBattleItemCardEvent` as **Battle Power-Up** with `battle_id`, `msg_type`, and `award_reason`. `msg_type` identifies critical strike, smoke, card award, extra time, special effect, potion, wave, Top 2/3, vault glove, etc. Keep deeper nested card objects out of generic template variables until a real action needs them.

## Event Registration Pattern (in `minecraft_main.py`)

```python
# 1. Import the event class
from TikTokLive.events import GameRankNotifyEvent

# 2. Decorate an async handler
@client.on(GameRankNotifyEvent)
async def on_game_rank_notify(event: GameRankNotifyEvent):
    u = event.user
    # ... do stuff
```

Handlers are async coroutines. The library dispatches them via the client's internal task queue.

## Where Event Metadata Lives

`event_registry.py` defines `EVENT_REGISTRY` — a dict mapping event name → metadata (class, display name, description, category, template vars, default priority). The UI uses this to expose "available events" to users for configuration.

**Every event you handle MUST also be in `event_registry.py`** with a `_evt()` entry. If it's only in the handler file, the UI can't let users configure actions for it.

## User Identification — Persistent Identity vs Display Names

The `User` proto (accessible via `event.user` on most events) carries multiple identifiers — use the right one depending on your use case:

| Field | Type | Changeable? | Use Case |
|---|---|---|---|
| `event.user.id` | **int** | ❌ Permanent | **Leaderboard keys, database ID, user tracking.** This is TikTok's internal numeric user ID. Never changes. |
| `event.user.id_str` | str | ❌ Permanent | Same as `id` but as string (JS-safe). |
| `event.user.sec_uid` | str | ❌ Permanent | Secure UID for API calls (user profile fetch, etc.). |
| `event.user.display_id` | str | ✅ Can change | The @handle/username (tiktok.com/@handle). User can rename. |
| `event.user.unique_id` | str | ✅ Can change | Alias for `display_id`. |
| `event.user.nickname` | str | ✅ Can change | Display name shown in chat. Can change anytime. |

**Leaderboard pattern:**

```python
# Permanent key = user.id; cosmetic display = user.nickname (update on every event)
leaderboard[event.user.id] = {
    "id": event.user.id,       # permanent, never changes
    "name": event.user.nickname,  # cosmetic, overwrite on each event
    "score": leaderboard.get(event.user.id, {}).get("score", 0) + points
}
```

**Gotchas:**
- `user.id` is an **int** — always cast to compare with other systems that might store it as string
- `user.nickname` can be empty for deleted/banned accounts — fall back to `display_id` or "Anonymous"
- `user.sec_uid` is the parameter used for TikTok profile URLs (`tiktok.com/@user?sec_uid=...`)
- **The project's existing `_user_unique_id()` helper is NOT a stable DB key.** It prefers `unique_id` (the changeable @handle) for avatar-cache friendliness. Code that needs a permanent identity (database PK, long-term per-viewer totals) must use `event.user.id` / `id_str` instead — a separate `_user_permanent_id()` helper was added for this in 2026-08-05. Don't reuse `_user_unique_id` for anything that must survive renames.
- **Shipped implementation of the leaderboard pattern:** the **Points tab** (2026-08-05) keys a SQLite ledger on `user.id`, refreshes nickname/username/avatar as cosmetic columns on every gift, and aggregates totals in an upserted `viewers` table (`points_store.py`, API at `/api/points/*`). If Khito asks for another long-term per-viewer tracker, copy that shape.

## Gift Event Data — Animation Detection & Asset Handling

Gift events carry extensive data about animations, effects, and display assets. This is how TikTok's client knows to play the fullscreen lion animation vs a simple rose popup.

### Quick Animation Detection

```python
# Best combo to detect "this gift has a full TikTok animation"
HAS_ANIMATION = (
    event.gift.is_effect_befview or       # fullscreen entrance effect
    event.is_asset_bundle_gift or          # has downloadable assets
    event.gift.is_broadcast_gift or        # broadcast across the room
    event.gift.is_global_gift or           # cross-screen animation
    event.gift.diamond_count >= 100        # empirical threshold
)
```

### Key Animation Data Fields

| Path | What it is |
|---|---|
| `event.gift.diamond_count` | Coin cost — TikTok's animation threshold is ~100+ |
| `event.gift.is_effect_befview` | **Has fullscreen entrance effect** (strongest signal) |
| `event.gift.is_broadcast_gift` | Broadcast/show-off gift |
| `event.gift.is_global_gift` | Cross-screen global animation |
| `event.gift.primary_effect_id` | Effect/animation ID |
| `event.gift.duration` | Animation duration (ms) |
| `event.asset.resource_url.url` | **Downloadable animation URL** (video/Lottie) |
| `event.asset.resource_type` | Asset type (1=image, 2=video) |
| `event.is_asset_bundle_gift` | Has bundle of animation assets |
| `event.asset_bundle.assets` | List of animation assets |
| `event.text_effect` | Text overlay layout (portrait + landscape) |
| `event.display_duration_ms` | How long to display |
| `event.effect_extra` | Raw extra effect config (JSON string) |
| `event.color_id` | Color variant of the gift |

### Link to Overlay

For the overlay HTML/JS show the gift animation:
- Download `event.asset.resource_url.url_list[0]` and render as a video element (if `resource_type=2`)
- Use `event.display_duration_ms` for the animation timeout
- Use `event.text_effect.portrait.background` for the text background image
- Use `event.text_effect.portrait.text` for the formatted text overlay

### Detecting the actual format (MP4 / WebM / Lottie)

The `resource_type` int enum is opaque. The **VideoResource** proto at `event.asset.video_resource_list` carries `video_type_name` (string like `"video/mp4"`, `"video/webm"`) and a `video_url` (a `ResourceModel` with its own `url_list`). If the gift has a video bundle, prefer `video_resource_list[0].video_url.url_list[0]` over the bare `resource_url` — it's the actual playable file.

For Lottie-style gifts: `event.asset.loki_content` (a `LokiExtraContent`) carries `view_overlay` (string), `model_names`, `bef_view_render_fps`, `bef_view_render_size` — these are the 3D effect descriptors TikTok's client uses to composite. Not directly playable in a browser `<video>`, so **cache the raw `resource_url` as JSON and let a future Lottie player consume it** if you need full fidelity. For a quick win, just play the `video_resource_list` URL if present.

### `interactive_gift_info` & cross-screen gifts

Some animated gifts trigger a room-wide effect (everyone sees it). Those set `event.interactive_gift_info.uniq_id` and have a `display_duration_ms` (ms) for how long the animation should run in the overlay. `event.interactive_gift_info.cross_screen_delay` is the ms delay before the animation fires on the recipient's screen.

### Reference

See `references/gift-proto-fields.md` for the complete field-level reference with all proto types and practical code examples.
See `references/gift-animation-assets.md` for the full asset field tree, format inference rules, real CDN domains, and a download/cache pattern with Flask serve route.
See `references/superfan-webcast-detection.md` for the SuperFan vs SuperFanBox Webcast detection notes and raw-event sniffing plan.
See `references/superfan-debug-dashboard-and-fallbacks.md` for the dashboard `Recent SuperFans` pattern, raw `BarrageEvent` primary detector, `JoinEvent` badge fallback, `UnknownEvent` probe, dedupe guard, and subdued join rendering.
See `references/superfan-barrage-recursive-scan.md` for the verified working SuperFan detector: `WebcastBarrageMessage` / `BarrageEvent` recursive string scan, observed `ttlive_superfan_commentnotif_someonebecamesuperfan` marker, and OBS overlay filter to show only `new_superfan`.
See `references/superfan-live-markers-2026-06.md` for live-tested routing details: new SuperFan vs join vs `super_fan_upgrade` false positive vs SuperFanBox `EnvelopeEvent` (`ttlive_superFanBox_commentSection_sent`, `business_type=UNKNOWN(19)`), richer Recent SuperFans payload fields, and temporary EulerStream legacy-host workaround.
See `references/superfan-box-envelope-confirmation-and-phase-logging.md` for source-confirmed `SuperFanBoxEvent -> EnvelopeEvent` inheritance, normal treasure-box vs SuperFanBox filtering, available `envelope_info` sender fields, and the `sent` / `claimed` / `unknown` phase logging pattern.
See `references/superfan-box-sent-claim-separation.md` for the SuperFan Box double-fire pattern: sender-side vs claim/open-side `EnvelopeEvent`, useful `envelope_info` fields (`send_user_name`, `send_user_id`, `diamond_count`, `people_count`, `envelope_id`), phase classification, and action safety rule.

## Discovery: Available Events

To find all event classes in the installed library:

```python
from TikTokLive.events import proto_events
print(sorted(proto_events.__all__))
```

Currently exposes ~60 events in a1, ~61 in b2 (new: `LinkMicBattleItemCardEvent`). Includes: `CommentEvent`, `LikeEvent`, `GiftEvent`, `FollowEvent`, `SubNotifyEvent`, `RoomUserSeqEvent`, `BarrageEvent`, `EnvelopeEvent`, `SuperFanEvent`, `SuperFanBoxEvent`, `GameRankNotifyEvent`, `RankUpdateEvent`, `RankTextEvent`, `HourlyRankRewardEvent`, `LinkMicBattleEvent`, **`LinkMicBattleItemCardEvent`** (b2+), `QuestionNewEvent`, `PollEvent`, `GoalUpdateEvent`, `OecLiveShoppingEvent`, `ViewerPicksUpdateEvent`, `ToastEvent`, `MarqueeAnnouncementEvent`, and many more.

**b2-added fields on existing events** (additive, non-breaking):
- `GiftEvent`: `secondary_effect_info`, `gift_variant_id`, `shiny_card_unlock_token`, `gift_effect`
- `LinkMicBattleEvent`: `cross_room_layout`, `tracking_extra`, `match_theme_display_resource`
- `LinkEvent`, `SubPinEventEvent`: `public_area_msg_common`
- `LinkLayerEvent`: `link_envelope_content`
- `GuideEvent`: `frequency_rule`

## Ranking & Leaderboard Events (high-value targets)

Four events cover rankings — **all currently imported but ZERO handlers in `minecraftDiamond.py`** as of 2026-06-04. Events fire and get discarded. Status: **data-collection only** via `rank_events.log` JSONL dumper.

| Event | Purpose | Key fields |
|---|---|---|
| `GameRankNotifyEvent` | Gaming rank notification (the user's "gaming ranking" target) | `msg_type`, `notify_text` |
| `RankUpdateEvent` | Streamer rank changed | `rank_priority`, `tabs`, `updates`, `tab_info` |
| `RankTextEvent` | Rank display text / badge | `content`, `rank_type`, `self_get_badge_msg` |
| `HourlyRankRewardEvent` | Hourly rank reward winners | `winners: list[HourlyRankRewardInfo]` |

**Why you might see nothing in the log:**
- Some events only fire on **MOBILE platform** (TikTok web client doesn't subscribe to them)
- Some events only fire at certain **streamer tiers** or live states
- Some events require the **bot account to have specific permissions** in the room

**Debug-logging pattern** (added 2026-06-04 in `minecraftDiamond.py`):

```python
def _dump_rank_event(event_name, event):
    try:
        payload = event.to_dict() if hasattr(event, "to_dict") else str(event)
    except Exception as conv_err:
        payload = f"<to_dict failed: {conv_err}>"
    line = json.dumps({"event": event_name, "ts": time.time(), "payload": payload},
                      default=str, ensure_ascii=False)
    print(f"======RANK EVENT: {event_name}======")
    print(line, flush=True)
    with _log_lock:
        with open("rank_events.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")

@client.on(GameRankNotifyEvent)
async def on_game_rank_notify(event: GameRankNotifyEvent):
    _dump_rank_event("GameRankNotify", event)
```

**To start seeing data on stream:** click `release\TikTokMCIntegrator.exe`, stream for a while, then `cat release/rank_events.log`. The JSONL is one event per line, fully searchable.

## Euler Stream Webcast Endpoints

Your library uses three endpoints. The **default base URL** changed in b2 (`WebDefaults.tiktok_sign_url`):
- a1 default: `https://tiktok.eulerstream.com`
- b2 default: `https://api.eulerstream.com`

The project **overrides** this at `minecraft_main.py:332` to `https://tiktok-legacy.eulerstream.com`, so the default change is a non-issue. The endpoints themselves are the same:

### 1. `GET /webcast/fetch` — WebSocket handshake (your lib uses this)

Query params: `client`, `room_id`, `unique_id`, `cursor`, `user_agent`, `client_enter`, `platform` (WEB|MOBILE), `session_id`, `tt_target_idc`.

Returns: **raw protobuf bytes** (`WebcastPushFrame` containing the WS URL + first `WebcastResponseMessage`). NOT JSON. Calling `response.json()` on it will fail.

Called from `TikTokLive/client/web/routes/fetch_signed_websocket.py:76-87`.

### 2. `POST /webcast/sign_url` — Per-request signer for ad-hoc HTTP calls

Body: `SignTikTokUrlBody { url, userAgent, method, sessionId, ttTargetIdc, ttwid, payload, type: "fetch"|"xhr", includeBrowserParams, includeVerifyFp }`

Returns: JSON `SignTikTokUrlResponse` with signed URL or signed request params.

Useful when you need to call TikTok's webcast REST API directly (e.g. `send_room_chat` for sending messages) without going through the full WebSocket flow. Already used by `test_signing.py` in this project.

### 3. `GET /webcast/region_rankings` — On-demand leaderboard poll

Params: `region` (OxyLabsProxyRegion), `rank_type` (RetrieveWebcastRankingsRankType), `session_id`, `tt_target_idc`, `x_oauth_token`, `x_cookie_header`.

Returns: JSON `WebcastRegionRankingsResponse` with current leaderboard for that region.

**This is the alternative to relying on real-time `GameRankNotifyEvent` pushes** — query it on demand when you want to display the current top gifters/rank.

## Gift Catalog Completeness — Union of Four Sources (2026-09-02)

`release/data/available_gifts.json` is a **union cache — never overwritten**. The old connect handler replaced it with the room panel on every connect (TikTok's panel is ~700 of ~2,800 gifts, `is_full_gift_data: False`), silently erasing learned gifts. Now:

- `gift_catalog.py` — union merge with per-field trust (`event` > `panel` > `region` > `euler`; history reuses the euler rank — `_SOURCE_RANK = {euler:0, region:1, panel:2, event:3}`); icons never downgrade to empty; entries without `id` rejected; every entry carries `in_panel`/`seen` room-scope flags.
- `gift_catalog_sync.py` — 20 Euler regional panels + full catalog (2,783 rows, pageSize ≤ 100); needs httpx + browser UA (plain urllib → Cloudflare 403).
- `gift_catalog_backfill.py` — recovers gifts from `gift_log.json` + `points.db` (price = GCD of observed totals); the only source for Super GG / KhitoFam.
- Every completed `GiftEvent` teaches the catalog its own gift before icon lookup — the only path for exclusive gifts.
- Dashboard: **Sync Gift Catalog** button → `POST /api/gifts/refresh`; connect-time sync runs off-loop via `asyncio.to_thread`.
- Gift scopes are intentionally distinct: `?scope=panel` = exact current TikTok room panel (`in_panel` only); `?scope=room` = current panel plus previously received (`in_panel OR seen`); absent/unknown scope = full union catalog. **Add/Edit Gift defaults to `panel` and must never silently fall back to the full catalog.** The operator may explicitly switch to **All known gifts**, with a warning that regional IDs may be unavailable. Duplicate gift names are resolved by exact gift ID, icon, and current-panel membership—not name or coin price.
- Verified result 2026-09-02: 701 → 2,789 gifts, zero losses; all 76 ever-received gifts priced. Room scope: 708.

Full detail, gotchas (icon string-vs-dict, Euler image host 403), and verification recipes: `references/gift-catalog-union.md`.

## Sending Chat — Paywalled via Euler (2026-09-02)

`client.web.send_room_chat` hard-requires a real `sessionid` and proxies Euler's **Webcast Premium** add-on (verified 401 with Community key; the generic `/webcast/sign_url` requires the $50/mo Business plan). The real lock is TikTok's signature tokens (`msToken`, `X-Bogus`, `X-Gnarly`). Options + credential-safety rules: `references/send-room-chat-feasibility.md`. The paid path ships the account cookie to Euler — do not set a session ID anywhere without Khito's explicit opt-in.

## Adding a New Event Handler — Checklist

1. **Import the class** in `event_registry.py`; import it in `minecraft_main.py` only if bespoke handling is required.
2. **Add an `_evt()` entry in `event_registry.py`** so the dashboard can configure dynamic actions.
3. **Choose generic vs bespoke handling:** the registry plus `register_dynamic_events()` is sufficient for template/action dispatch; write `@client.on(EventClass)` only for custom state, filtering, dedupe, overlays, or persistent logging.
4. **Expose stable scalar variables first.** Validate them with a constructed real event through `build_context`; avoid dumping nested proto objects into commands.
5. **Add release-contract regression coverage** for the matched package pins and registry entry.
6. **Verify source and frozen runtime:** full tests, fresh dependency install, Windows build-Python check, `./deploy.sh --full`, then frozen `/health` + `/api/event-registry` smoke tests.
7. **Test on live stream only after offline gates pass** — capture initial real payloads before adding higher-impact behavior.

## Pitfalls

- **All handlers are async** — `await` is required for `execute_actions()`, `send_minecraft_command()`, etc. Forgetting `await` silently breaks the call.
- **No type hints are enforced** — the library returns pydantic-typed objects but your handler signature can be `event: SomeEvent` or just `event` — be explicit for grep-ability.
- **Events may fire while the client is reconnecting** — guard with try/except, log the error, don't crash the worker loop.
- **Some events are mobile-only** — if a handler never fires, try `WebcastPlatform.MOBILE` instead of WEB (requires `sessionid` cookie).
- **SuperFan vs SuperFanBox are different proto paths; wrappers can miss events.** SuperFanBox is `EnvelopeEvent` with `ttlive_superfanbox` or `business_type == 19`; in current TikTokLive, `SuperFanBoxEvent` may have no `.user`, so never assume `event.user` exists for box events. General SuperFan/new-superfan usually appears through `WebcastBarrageMessage` / `BarrageEvent`, but fixed fields may be empty; use recursive string scan. Classify specific markers before generic substrings: join marker `ttlive_superfan_commentnotif_superfanjoined` = log-only/no reward; upgrade marker `super_fan_upgrade` / `superfan_upgrade` = log-only/no reward; new markers `ttlive_superfan_commentnotif_someonebecamesuperfan`, `becoming_super_fan*`, `becomingsuperfan*` = new-superfan overlay + reward/action. See `references/superfan-webcast-detection.md`, `references/superfan-debug-dashboard-and-fallbacks.md`, and `references/superfan-live-markers-2026-06.md`.
- **SuperFan Box double-fires: separate send from claim/open before actions.** SuperFan Box can emit once when the box is sent/created and again when someone opens/claims it, while TikTok's UI shows both almost the same (`Someone opened / triggered SuperFan Box`). In current TikTokLive it is an `EnvelopeEvent` / `SuperFanBoxEvent`; `event.user` may be missing, so use `event.envelope_info.send_user_name` / `send_user_id` for sender data and `envelope_id` for correlation/dedupe. Classify into `superfan_box_sent`, `superfan_box_claimed`, or `superfan_box_unknown`. Only `superfan_box_sent` should execute configured `SuperFanBoxEvent` actions by default; claim/open/unknown events are log/feed-only while collecting marker samples. See `references/superfan-box-sent-claim-separation.md`.
- **Don't `print` large payloads naively** — `to_dict()` on a rank update can be 50KB. Use the JSONL file pattern, not stdout, for high-volume debugging.
- **Gift asset downloader toggle must be wired end-to-end.** `Settings.GiftAssetDownloader` is live-read per gift; if the dashboard checkbox is not populated/saved, the UI can look OFF while `release/config/config.yml` remains `true`, causing download attempts during streams. Current folderized import is `assets.gift_assets.downloader`; dynamic import requires PyInstaller hidden imports. See `references/gift-asset-downloader.md`.
- **Streak-delta gift counters must update before awaited actions and must not pop final state immediately.** TikTok streak gifts are repeat_count snapshots (`1 → 2 → 5`, final summary) and configured delta gifts still execute the regular gift action with `{amount}=delta`. If code does `prev = tracker[group_id]`, then `await execute_actions(...)`, then writes `tracker[group_id] = repeat_count`, overlapping `GiftEvent` handlers can all read stale `prev=0` and over-trigger rewards (e.g. 5 ice cream cones giving 8+ totems). Also, popping the tracker on final `repeat_end` lets duplicate final events re-trigger the full amount. Correct pattern: atomically record the highest seen count before any await, return `max(0, repeat_count - previous)`, keep ended entries for a short TTL to ignore duplicate finals, then cleanup later.
- **`EVENTS.get("X", EVENTS.get("Y", []))` reward fallback is a silent leak — NEVER chain a non-new SuperFan sub-event to the `SuperFan` actions.** Bug found 2026-06-11: `_trigger_superfan_box` used `EVENTS.get("SuperFanBoxEvent", EVENTS.get("SuperFan", []))`. Since `config.yml` has a `SuperFan:` section (the reward) but no `SuperFanBoxEvent:` section, a SuperFanBox fell through to running the full **new-SuperFan reward** (sound/MC actions). Symptom: "superfanbox triggers my superfan event, but it should only show in the feed." Fix: drop the fallback — `EVENTS.get("SuperFanBoxEvent", [])`. With no box actions configured, a box is now log/feed-only (the intended behavior). **General rule: a fallback action lookup must NEVER default to a *different, heavier* event's actions. Default to `[]` (no-op) instead.** Each SuperFan sub-type (`superfan_join`, `superfan_upgrade`, `superfan_box`) is log-only unless it has its OWN explicitly-configured event section; only genuinely-new markers (`ttlive_superfan_commentnotif_someonebecamesuperfan`, `becoming_super_fan*`) fire the `SuperFan` reward + OBS overlay. The OBS overlay filter (`overlay.html` ~line 1098, `event_type === 'new_superfan'`) is separately correct — boxes never popped the visual alert; the leak was purely the action-fallback.
- **Gift catalog writes must be union merges, never replacement.** Any code tempted to write `available_gifts.json` wholesale (room panel, UI import) must go through `gift_catalog.merge_into_catalog`. Wholesale replacement was the root cause of the 2026-09 "missing gifts" bug (Super GG / Game Controller / KhitoFam losing icons on every connect). See `references/gift-catalog-union.md`.
- **Never let a full-catalog preload contaminate the precise picker pool.** Icon/name preloading may populate `cachedAllGifts`, but never `cachedAvailableGifts`; otherwise the modal's early-return path bypasses `?scope=panel` and displays regional duplicate IDs. Verify a known duplicate family against the released API and rendered modal, not merely source tests.
- **Custom dropdowns inside themed cards need a clipping check.** The shared Gifts-card theme applies `overflow:hidden`; an absolutely positioned picker can therefore render only 1–2 rows despite a large `max-height`. Give the specific interactive card `overflow:visible` plus an appropriate stacking context, then pixel-check the open list in the released UI.
- **Session-ID facts are measured, and phrasing matters:** the gift list is unsigned and unaffected by `user_is_login` (dummy-session test: identical 701/703 panels); session ID's only uses are age-restricted rooms, `send_room_chat`, and MOBILE platform. When reporting auth experiments, always state whether a real credential or a dummy was used — Khito corrected "with a session ID set" as implying his real credential was in play. See `references/send-room-chat-feasibility.md`.
- **Delayed action execution must live on the event loop, never `threading.Timer`.** `execute_actions` is async (`asyncio.gather`), so a bare timer thread cannot await it; and `client.run()` RETURNS on stream end/heartbeat drop while `run_bot()` re-invokes it, so a timer outliving the loop targets a dead loop. Pattern: reserve synchronously, then `asyncio.create_task(sleep→execute)` inside the handler — the task auto-cancels with the loop. Never resume/replay a pending delayed action after a process restart (stale state = cancelled at startup; duplicate destructive commands are worse than a lost one).
- **Delayed-action execution must go through `minecraft_main.execute_actions` (the Log Only-gated wrapper), never raw `actions.execute_actions`.** The wrapper live-reads Log Only Mode at execution time, so a mid-delay toggle is honored at land. Importing the raw function (as `gift_simulation.py` does) bypasses the gate entirely. Feature modules that need both should accept the executor as an injected callable.
- **Config hot-path reads use the hot-reload snapshot, not per-event YAML.** New per-event features must add their config block to `reload_config()`'s globals (normalized once at startup/reload); do NOT open/parse `config.yml` inside a TikTok event handler — the dispatch boundary is latency-critical and per-event YAML parse violates it. Dashboard saves already apply live via `signal_reload` + the 3s watcher.
- **Dashboard-process action execution must run `migrate_config_actions(load_config())` first.** On-disk profile YAML still holds legacy raw-string action lists; `app.load_config()` only runs `migrate_to_events_redesign`, and `execute_actions` silently skips non-dict actions — so any dashboard-side executor that resolves actions straight from `load_config()` runs ZERO commands on string-format profiles. The bot process is safe because it migrates in memory at startup/reload.
- **Bot and dashboard are separate processes: never schedule the same side-effecting work in both.** In-memory locks are process-local; a shared JSON state file gives atomic writes, not coordination. Gate executable dashboard endpoints on `is_any_bot_running()` (HTTP 409 while live) rather than inventing cross-process locking, and tag shared state files with their source process so overlaps are diagnosable.
- **Integration tests for delayed/loop-scheduled dispatch must run inside ONE `asyncio.run(scenario())`.** Back-to-back `asyncio.run()` calls close the first loop and cancel its pending background tasks (a delayed spin/action never dispatches) — code that fails only under pytest but works standalone usually has a cross-loop test, not a code bug. Test doubles must also mirror the real contract's reject paths (busy/cooldown/dedupe), not just the happy path.

## Reference Files

- `references/euler-webcast-endpoints.md` — Complete reference for the 3 Euler endpoints with request/response examples
- `references/gift-proto-fields.md` — Full field-level reference for gift animation data (assets, text effects, thresholds, practical code)
- `references/gift-gallery-proto-fields.md` — Gift Gallery proto types: `GiftPanelUpdateEvent` (gallery progress tracking), `GalleryData`/`TitleData`, `BarrageTypeGiftGalleryParam`, `GiftGalleryBadgeInfo`/`GiftGalleryBadgeSection` (PK battle league badges). Includes current bot handler status and wiring pattern.
- `references/gift-asset-downloader.md` — Working pattern for on-demand gift animation asset caching (opt-in toggle, manifest store, Flask serve, path-traversal guard)
- `references/tiktoklive-7.0.0b2-upgrade-audit.md` — Full diff audit of TikTokLive 7.0.0a1 → 7.0.0b2: signatures, monkey-patch status, new events/fields, dependency bumps, Euler URL change, PyInstaller impact
- `references/gift-catalog-union.md` — Union-merged `available_gifts.json`: four sources, trust ranking, live-event self-learning, strict current-panel vs room/full scopes, duplicate-name picker UX, cache-contamination pitfall, icon/Euler/CDN gotchas, verification recipes
- `references/gift-action-simulation.md` — Offline Gift Simulator contract: real action dispatcher, placeholder context, side-effect boundary, icon-aware picker, and released-runtime verification
- `references/send-room-chat-feasibility.md` — Why sending chat is paywalled (verified 401s), the real signature-token lock, credential-safety rules, and the three self-serve options
