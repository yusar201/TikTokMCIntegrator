# v7 Research Findings — 2026-04-30 Session

## Package Structure (v7.0.0a1 as installed in a bare venv)

```
~/.hermes/hermes-agent/venv/lib/python3.11/site-packages/TikTokLive/
  __init__.py
  __version__.py
  events/
    __init__.py           — Event union type, exports
    base_event.py         — BaseEvent class
    proto_events.py       — All proto-backed events (1605 lines, ~50 event classes)
    custom_events.py      — SuperFanEvent, SuperFanJoinEvent, SuperFanBoxEvent, FollowEvent, ShareEvent, etc.
  proto/
    __init__.py
    proto_utils.py
    custom_proto.py       — ExtendedUser, ExtendedGift
    _aliases.py
  client/
    web/                  — Web routes, signer, settings
    ws/                   — WebSocket client
```

## Key Dependencies

- `betterproto2` — NOT `betterproto` (this is why camelCase crash is fixed)
- `TikTokLiveProto` — Separate protobuf package (Schema V3, slimmed)
- `mashumaro` — Serialization
- `protobuf3-to-dict` — Proto to dict conversion
- `EulerApiSdk` — Euler API SDK for signer

## Event Changes (v6 → v7)

### Events renamed
- `SubscribeEvent` → `SubNotifyEvent` (WebcastSubNotifyMessage)
  - New fields: `subscribe_type` (enum), `sub_month` (int), `subscribing_status`, `old_subscribe_status`, `message_type`

### Events with new user access
- `SuperFanEvent` (BarrageEvent) — NOW has `event.user: ExtendedUser` (v6 required barrage text parsing)
- `SocialEvent` (FollowEvent parent) — `event.user: ExtendedUser`, `follow_type`, `follow_count`
- `GiftEvent` — `event.user: ExtendedUser`, `event.gift` is `ExtendedGift`
- `CommentEvent` — `event.user: ExtendedUser`, `event.comment`

### New events
- `SuperFanJoinEvent` (BarrageEvent) — existing superfan joins stream
- `SuperFanBoxEvent` (EnvelopeEvent) — superfan gift box delivered

### RoomUserSeqEvent field changes
```
v6: m_total, m_popularity, total_user
v7: total_user, popularity, total, pop_str, anonymous, ranks, seats
```

## ExtendedUser Properties (from custom_proto.py)

Source: `~/.hermes/hermes-agent/venv/lib/python3.11/site-packages/TikTokLive/proto/custom_proto.py`

| Property | Returns | Implementation |
|----------|---------|---------------|
| `unique_id` | str? | `self.display_id or None` (alias for @-handle) |
| `is_friend` | bool | `follow_info.follow_status >= 2` |
| `is_moderator` | bool | `_get_badge_level("ADMIN") == 0` |
| `is_top_gifter` | bool | `_get_badge_level("RANK_LIST") == 0` |
| `member_level` | int? | `_get_badge_level("FANS")` |
| `member_rank` | int? | Alias for `member_level` |
| `gifter_level` | int? | `_get_badge_level("USER_GRADE")` |
| `has_badge(type, level?)` | bool | General badge checker |
| `get_all_badges` | [(str,str)] | All badges with (type, level) |
| `follow_info` | FollowInfo | follower_count, following_count, follow_status |

## Proto Schema V3 — Key Proto Files

GitHub: `isaackogan/TikTok-Webcast-Protobuf`, path `src/slim/v3/webcast/`

- `model/base/user.proto` — User, BadgeStruct, FansClubInfo, FollowInfo, SubscribeInfo
- `model/data/messages.proto` — Enums: BadgeDisplayType (FRIENDS, SUBSCRIBER, FANS, etc.)
- `model/message/common.proto` — Contributor, CommonMessageData
- `model/message/ext.proto` — HotTag, PopProduct

## TikTokMCIntegrator Upgrade Summary (2026-04-30)

File changed: `minecraftDiamond.py`

| # | Change | Lines |
|---|--------|-------|
| 1 | Imports: SubscribeEvent→SubNotifyEvent, add SuperFanEvent/SuperFanBoxEvent | 3 |
| 2 | Delete `get_user()` helper | -10 |
| 3 | Replace `get_user(event)` → `event.user` (4 call sites) | 4 |
| 4 | SubscribeEvent→SubNotifyEvent handler with sub type tracking | +4 |
| 5 | SuperFanEvent: kill barrage parsing, use `event.user` directly | -15, +6 |
| 6 | Add SuperFanBoxEvent handler | +6 |
| 7 | RoomUserSeq: m_total→total_user, m_popularity→popularity | 2 |
| 8 | Follower/friend: 18-line manual parsing → 4-line ExtendedUser properties | -14 |

**Net: -70 removed, +32 added. Syntax verified clean.**

## User Preferences (Ikhito)

- **Do NOT listen to SuperFanJoinEvent** — only SuperFanEvent (new superfans) and SuperFanBoxEvent (gift boxes). Join notifications are noise.
- **Keep `EVENTS.get("SuperFan", [])` commands** for all superfan-related events — fire the same Minecraft rewards regardless of event type.
- **No em-dashes in output** — they render as escaped unicode in the user's terminal.

## Session 2 Findings — 2026-04-30 (Upgrade Attempt #2)

### Critical Pitfall: Wrong Python Version Check
Checked `pip show TikTokLive` with a bare `pip` → v7.0.0a1. But the project's interpreter (`C:\Python313\python.exe`) had **v6.6.5**. Made all v7 code changes before installing v7 into the right interpreter → immediate `ImportError: cannot import name 'SubNotifyEvent'`.

**Lesson:** Always confirm the TARGET interpreter's version. Confirm the TARGET interpreter (`C:\\Python313\\python.exe`) before installing anything — a bare `pip` may hit the wrong Python.

### v7 Alpha: Custom Event Dispatch Instability
v7 alpha's `handle_custom_event()` dispatches `SuperFanEvent`/`SuperFanBoxEvent` as subclasses alongside parents. The `WebsocketResponseEvent` base wrapper fires for every message — the "unknown" events user saw were these wrappers (normal).

But subclass handlers (`@client.on(SuperFanEvent)`) may not fire reliably in alpha. **Safer fallback:** subscribe to parent events and filter by `common_display_type`:

```python
from TikTokLive.proto.proto_utils import common_display_type

@client.on("barrage")   # parent of SuperFanEvent
@client.on("envelope")  # parent of SuperFanBoxEvent
```

Match markers: `ttlive_superfan` (new superfan), `ttlive_superfan_commentnotif_superfanjoined` (join — skip), `ttlive_superfanbox` (gift box). Mirrors library internals exactly.

### Project Backup Exists
Path: `D:\Ikhito\Code\backups\TikTokMCIntegrator_backup_20260429_113330.tar.gz`
- Contains full project tree under `TikTokMCIntegrator/` subfolder
- Restore: `tar xzf <backup> -C /tmp/restore; cp /tmp/restore/TikTokMCIntegrator/minecraftDiamond.py <project>/`

### Tag Rename: is_subscriber → is_superfan
User wanted comment detection variable renamed from `is_subscriber` to `is_superfan`. Same logic (checks `member_level` from FANS badge). Log tag stays `"subs"`.
