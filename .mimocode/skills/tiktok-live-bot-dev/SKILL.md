---
name: tiktok-live-bot-dev
description: "TikTokMCIntegrator development: events, overlays, live config, Spotify, TTS, reconnects, packaging, and OneBlock. References: oneblock-objective-rush-design.md and oneblock-tiktok-chaos-design.md."
trigger: "TikTokMCIntegrator, TikTok Live events, RCON latency, Minecraft command dispatch, connector performance, overlays, live config, Spotify queue, reconnects, TTS, packaging, OneBlock"
---

# TikTok Live Bot Development

Connector/performance references:
- Connector performance + dashboard console/reconnect: `references/rcon-low-latency-dispatch.md`, `references/dashboard-console-clear-and-reconnect-readability.md`

OneBlock references:
- Runtime, counters, selection, invariants, Flask lifecycle, headless play mode, and operator score/goal extension controls: `references/oneblock-objective-rush-runtime.md`
- Gameplay design: `references/oneblock-objective-rush-design.md`
- Add-on filtering, presets, matching overlay visuals, Minecraft event effects, deployment: `references/oneblock-addon-objective-feedback.md`
- Native Minecraft sidebar for Objective Rush state, parser/scoreboard invariants, and fixture verification: `references/objective-rush-minecraft-sidebar.md`
- Isolated `--objective-rush` Minecraft-only runtime, import-order isolation, one-click launcher, and end-to-end verification: `references/objective-rush-ingame-sidebar-headless-runtime.md`

TikTokLive Python library integration for game-server bots (Minecraft RCON, etc.). Covers library update research, event structure understanding, user property access, migration between major versions, and TikTokMCIntegrator project config management.

## Quick Reference

### User Preferences (Ikhito)

| Preference | Detail |
|------------|--------|
| Overlay style | Compact, corner-friendly, bigger text, center-aligned. NOTHING shown when empty — no placeholder text. |
| Logs / checkpoints | During active debugging, do NOT pause to write progress summaries after every tiny fix. The user explicitly says "we still debugging" to signal verbosity should be minimal until the bug is resolved. Brief answers, no process plumbing. Only log comprehensively when the user says "log it" / "save checkpoint" on a completed feature. **When the user says "log it":** (1) write a comprehensive daily log entry to `D:/path/to/Obsidian Vault/Agent-Hermes/daily/YYYY-MM-DD.md` covering ALL changes made that session, not just the latest feature, (2) run `graphify update . --force` on the project to rebuild the knowledge graph, and (3) update `working-context.md` with a brief feature summary entry. |
| Fact-checking | User fact-checks and hates analysis paralysis. Give the winning answer first; options only if asked. "Brief it down" = concise summary with no tool logs. |
| Simplicity over heuristics | When designing sync logic, state machines, or detection patterns, user prefers **simple explicit rules** (track change, play/pause flip, visibility change) over heuristic drift detection, threshold-based re-sync, or complex interpolation. Only add a 4th rule (e.g. seek detection) if the user explicitly asks for it after you present the minimal 3-rule version. Do NOT proactively add "smart" drift detection — it causes periodic jumps and the user will tell you to remove it. |

| Concern | v6 (old) | v7 (7.0.0a1) |
|---------|----------|--------------|
| Protobuf engine | `betterproto` (camelCase crashes) | `betterproto2` |
| Proto package | Bundled | Separate: `TikTokLiveProto` (Schema V3) |
| User access | `get_user(event)` helper needed | `event.user` (raw User proto — **must** convert via `ExtendedUser.from_user(event.user)` to get properties) |
| SuperFan | Broken/hacky | 3 proper events |
| Follow | Via SocialEvent parsing | `FollowEvent` + `event.user.is_friend` |
| Subscribe | Manual proto parsing | `SubNotifyEvent` + user badges |

## How to Research a TikTokLive Update

When a new version drops, DO NOT rely on PyPI README or GitHub changelog — they are often missing. Instead, read the installed package source directly:

```bash
# Find the package
python3 -c "import TikTokLive; print(TikTokLive.__path__)"

# Then read in order:
# 1. events/proto_events.py  — all proto-backed events + their TYPE_CHECKING fields
# 2. events/custom_events.py — custom events (SuperFan, Follow, Share, etc.)
# 3. proto/custom_proto.py   — ExtendedUser & ExtendedGift with helper properties
# 4. events/__init__.py      — exports and Event union type
```

Focus on: event class hierarchy (what proto message each extends), `user` field presence, new helper properties on ExtendedUser, and TYPE_CHECKING blocks for field signatures.

## Event Hierarchy (v7)

### Proto Events (proto_events.py)
All extend both `BaseEvent` and their proto message class. Key ones:
- `SocialEvent(WebcastSocialMessage)` — user, follow_count, follow_type, share_count
- `RoomUserSeqEvent(WebcastRoomUserSeqMessage)` — `total` (current viewers), `total_user` (cumulative all-time), `popularity`, `ranks`, `seats`. **Ikhito prefers `total` for primary display, no popularity.**
- `SubNotifyEvent(WebcastSubNotifyMessage)` — user, subscribe_type, subscribing_status
- `GiftEvent(WebcastGiftMessage)` — user, gift, repeat_count, streak info
- `CommentEvent(WebcastChatMessage)` — user, content

### Custom Events (custom_events.py)
- `FollowEvent(SocialEvent)` — dedicated follow event
- `ShareEvent(SocialEvent)` — share tracking with `users_joined` property
- `SuperFanEvent(BarrageEvent)` — triggered when viewer BECOMES superfan (ttlive_superfan marker)
- `SuperFanJoinEvent(BarrageEvent)` — existing superfan joins stream
- `SuperFanBoxEvent(EnvelopeEvent)` — superfan gift box delivered

## Schema V3 Field Renames (v6 → v7)

Several User proto fields were renamed between Schema v2 and v3. Code that hardcodes old names will silently fail:

| v6 field | v7 Schema V3 field | Notes |
|----------|-------------------|-------|
| `nick_name` | `nickname` | Display name. Old name returns empty/Nothing → Minecraft shows `<none>` |
| `badges` | `badge_list` | Badge array on User proto |
| `badge_scene` | `scene_type` | Now an enum (`BadgeSceneType`), not a string |
| `log_extra` | `privilege_log_extra` | Badge metadata container |
| `log_extra.level` (int) | `privilege_log_extra.level` (str) | Level is now a string |

**Safe access pattern:** `getattr(obj, 'newname', getattr(obj, 'oldname', default))`

## ExtendedUser Properties (v7)

Access via `event.user` on any event that carries a user. Key properties:

| Property | Returns | How |
|----------|---------|-----|
| `is_friend` | bool | `follow_info.follow_status >= 2` |
| `is_follower` | ❌ N/A | **NOT a property.** Use `follow_info.follow_status == 1` instead. The `is_follower` proto field (field 1029) on User is often unpopulated. |
| `is_super_fan` | ❌ N/A | **NOT a property.** Use `event.user_is_super_fan` on CommentEvent (checks `user_identity.is_subscriber_of_anchor`). No ExtendedUser property exists. |
| `is_moderator` | bool | ADMIN badge level == 0 |
| `is_top_gifter` | bool | RANK_LIST badge level == 0 |
| `member_level` | int? | FANS badge level (heart-me-gift member, not superfan). Do NOT use for superfan check. |
| `member_rank` | int? | Alias for member_level |
| `gifter_level` | int? | USER_GRADE badge level |
| `unique_id` | str? | Alias for display_id (@-handle) |
| `has_badge(type, level?)` | bool | Check any badge |
| `get_all_badges` | [(str,str)] | All badges with levels |
| `follow_info` | FollowInfo | follower_count, following_count, follow_status |
| `avatar_thumb` | ImageModel | Profile picture — access URL via `user.avatar_thumb.url_list[0]` |
| `avatar_medium` | ImageModel | Medium-size avatar |
| `avatar_large` | ImageModel | Large-size avatar |

## Step-by-Step Upgrade Checklist (v6 to v7)

When upgrading a TikTokMCIntegrator-style bot from v6 to v7, follow this order:

1. **Update imports** — Remove `SubscribeEvent`, add `SubNotifyEvent`. Pull `SuperFanEvent, SuperFanBoxEvent` from `TikTokLive.events.custom_events`.
2. **Delete `get_user()` helper** — betterproto2 makes it unnecessary. Replace all callers with `event.user` directly.
3. **SubscribeEvent → SubNotifyEvent** — v7 renamed it. New fields: `subscribe_type`, `sub_month`, `subscribing_status`.
4. **Rewrite SuperFan handler** — Kill the barrage text-parsing workaround. `event.user` works now. Split into `SuperFanEvent` (new superfans only) and `SuperFanBoxEvent` (gift boxes). **User preference: skip SuperFanJoinEvent** — joining notifications are unwanted noise.
5. **Fix RoomUserSeqEvent fields** — `m_total` → `total_user`, `m_popularity` → `popularity`. v7 Schema V3 dropped the `m_` prefixes.
6. **Simplify detection** — ExtendedUser properties only work AFTER `from_user()` conversion. Raw proto fields always work:
   - **Superfan:** `event.user_is_super_fan` (on CommentEvent proto, NOT a user property)
   - **Friend:** `follow_info.follow_status >= 2` (read from proto directly)
   - **Follower:** `follow_info.follow_status == 1` (read from proto directly)
   - **Member:** `member_level` property on ExtendedUser (FANS badge, requires `from_user()` + monkey-patch)
   - ⚠️ `is_super_fan` and `is_follower` do NOT exist as ExtendedUser properties in v7
7. **Extract avatar if needed** — `event.user.avatar_thumb.url_list[0]` gives the profile picture URL. `avatar_medium` and `avatar_large` also available.

Expected stats: ~70 lines removed (get_user + barrage parsing + manual detection), ~40 lines rewritten. Net cleaner.

## Event Name Changes (v6 to v7)

| v6 Name | v7 Name | Notes |
|---------|---------|-------|
| `SubscribeEvent` | `SubNotifyEvent` | Renamed. Has user, subscribe_type, sub_month |
| `SuperFanEvent` (v6) | `SuperFanEvent` (v7) | Now has `event.user` directly. No more barrage parsing needed. |
| _(none)_ | `SuperFanJoinEvent` | Existing superfan joins. Ikhito does NOT want this. |
| _(none)_ | `SuperFanBoxEvent` | Superfan gift box delivered. Ikhito wants this. |

## Migration Patterns (v6 to v7)

### Removing get_user()
In v6, a custom `get_user(event)` helper was needed to work around betterproto camelCase crashes. In v7, delete it — events expose `event.user` directly as ExtendedUser.

```python
# v6 (DELETE THIS)
def get_user(event):
    return event.user if hasattr(event, 'user') else None

# v7 (BUILT-IN)
user = event.user  # ExtendedUser, already parsed
```

### SuperFan Detection (v7 — class-based only)

Use class-based event handlers only. **Do NOT use string subscriptions** like `@client.on("barrage")` — v7's `on()` method expects event classes, not strings. `AttributeError: 'str' object has no attribute 'get_type'`.

```python
from TikTokLive.events.custom_events import SuperFanEvent, SuperFanBoxEvent

@client.on(SuperFanEvent)
async def on_superfan(event: SuperFanEvent):
    """Fires when someone BECOMES a new superfan (NOT when existing superfan joins)."""
    # v7 Schema V3 renamed nick_name → nickname; fallback for safety
    nick = getattr(event.user, 'nickname', getattr(event.user, 'nick_name', 'Unknown'))
    print(f"SuperFan: {nick}")
    ...

@client.on(SuperFanBoxEvent)
async def on_superfan_box(event: SuperFanBoxEvent):
    """Fires when someone gifts a superfan box/bundle."""
    nick = getattr(event.user, 'nickname', getattr(event.user, 'nick_name', 'Unknown'))
    print(f"SuperFan Box from: {nick}")
    ...

# Ikhito does NOT want SuperFanJoinEvent — skip it.
```

This replaces the v6 workaround (barrage text parsing for nick extraction). v7's `event.user` provides `nick_name`, `unique_id`, etc. directly on every custom event.

### Friend/Follower/Superfan Check
```python
# ⚠️ IMPORTANT: event.user is a raw User proto in v7 alpha.
# Convert to ExtendedUser first to access properties:
from TikTokLive.proto.custom_proto import ExtendedUser
u = ExtendedUser.from_user(event.user) if event.user else None

# Superfan — only available via event.user_is_super_fan (on CommentEvent proto)
is_superfan = event.user_is_super_fan  # checks user_identity.is_subscriber_of_anchor

# Friend/Follower — read follow_info.follow_status from proto directly
# 0=not following, 1=follower (one-way), 2+=friend (mutual)
follow_status = getattr(getattr(u, 'follow_info', None), 'follow_status', 0) if u else 0
is_friend = follow_status >= 2
is_follower = follow_status == 1

# Member — uses ExtendedUser.member_level (requires from_user + monkey-patch for v7)
is_member = bool(getattr(u, 'member_level', 0)) if u else False

# Or listen to FollowEvent directly:
@client.on(FollowEvent)
async def on_follow(event: FollowEvent):
    print(f"New follower: {event.user.nickname}")
```

### Avatar / Profile Picture Extraction
```python
# v7 ExtendedUser exposes avatar_thumb, avatar_medium, avatar_large (ImageModel)
# Get the CDN URL: user.avatar_thumb.url_list[0]
avatar_url = ""
try:
    thumb = getattr(event.user, 'avatar_thumb', None)
    if thumb and getattr(thumb, 'url_list', None):
        avatar_url = thumb.url_list[0]
except Exception:
    pass
```

## Upgrade Procedure (CRITICAL — read before modifying any code)

**⛔ DO NOT SKIP STEP 1.** This was violated on 2026-04-30 and caused a wasted session.

1. **Verify the TARGET Python's library version FIRST.** The project runs on `C:\Python313\python.exe` — check it directly: `C:\Python313\python.exe -m pip show TikTokLive`. A bare `pip show` may hit a different interpreter.
2. **Install v7 BEFORE making any v7-specific code changes.** Otherwise imports crash (`ImportError: cannot import name 'SubNotifyEvent'`).
3. **After install, verify imports work** before proceeding with the upgrade steps. Check: `python -c "from TikTokLive.events import SubNotifyEvent; print('OK')"`.
4. **When making many changes to a file, prefer writing the complete final file over many small find/replace edits.** Multiple incremental patches can leave the file in an inconsistent state if one fails mid-way. For major upgrades, compose the full file and write it in one shot. Keep the backup tar.gz handy for quick restores.

## v7 Alpha Known Bugs

### `log_id` validation crash (GitHub issue #361)
`WebcastPushFrame.log_id` has `ge=0` Pydantic validation but TikTok sends `-1`. Fix:
```bash
# In the TARGET Python's site-packages:
# TikTokLiveProto/v3/webcast/im/__init__.py line 1625
# Change: ge=0 → ge=-1

# One-liner monkey-patch (run from the user's Windows terminal):
python -c "import TikTokLiveProto, os; f=os.path.join(os.path.dirname(TikTokLiveProto.__file__),'v3/webcast/im/__init__.py'); c=open(f).read(); open(f,'w').write(c.replace('ge=0, le=2','ge=-1, le=2')); print('PATCHED')"
```
This will be fixed when the dev merges the PR — remove the monkey-patch after updating.

**⚠️ Apply to the TARGET Python:** Run the one-liner with `C:\Python313\python.exe` — the interpreter that executes the bot and builds the exe — not a bare `python`.

### `_get_all_badge_info` broken for v3 Schema (3 wrong field names)
In v7.0.0a1, `ExtendedUser._get_all_badge_info()` references v2 field names. Schema V3 renamed:

| v2 field | v3 field |
|----------|----------|
| `self.badges` | `self.badge_list` |
| `badge.badge_scene` | `badge.scene_type` (enum `BadgeSceneType`) |
| `badge.log_extra` | `badge.privilege_log_extra` (`PrivilegeLogExtra`) |
| `log_extra.level` (int) | `privilege_log_extra.level` (str) |

This breaks ALL badge-based properties: `member_level` (FANS=10), `gifter_level` (USER_GRADE=8), `is_moderator` (ADMIN=1), `is_top_gifter` (RANK_LIST=6).

**Fix (monkey-patch in minecraftDiamond.py):** Must handle enum `.name` extraction + `privilege_log_extra` + string level. See the monkey-patch block after imports.

## Comment Tag Hierarchy (Ikhito's System)

Ikhito uses a multi-badge tag system for Minecraft chat display via `/chatlog` RCON command:

**Hierarchy:** VIP > SuperFan > Member > Friend > Follower > Newbie

**Rule:** VIP users show ALL their applicable badges. Non-VIP show only the highest single tag.

**Tag format:** Comma-separated string passed as arg-1 to `/chatlog` (e.g., `"vip,superfan,member"`).

**Detection in Python:**
```python
is_vip = uid in VIP_LIST
# ⚠️ is_super_fan is NOT an ExtendedUser property — use event.user_is_super_fan (on CommentEvent)
is_superfan = event.user_is_super_fan  # checks user_identity.is_subscriber_of_anchor
is_member = bool(getattr(u, 'member_level', 0)) if u else False   # FANS badge level (heart-me-gift member)
# Follower/Friend: use follow_info.follow_status
#   0=not following, 1=follower (one-way), 2+=friend (mutual)
follow_status = getattr(getattr(u, 'follow_info', None), 'follow_status', 0) if u else 0
is_friend = follow_status >= 2
is_follower = follow_status == 1

# Accumulate all matching tags (highest first)
tags = []
if is_vip:     tags.append("vip")
if is_superfan: tags.append("superfan")
if is_member:  tags.append("member")
if is_friend:  tags.append("friend")
if is_follower: tags.append("follower")
if not tags:   tags = ["newbie"]

# VIP shows all badges, others show only highest
if "vip" not in tags:
    tags = [tags[0]]

tag_str = ",".join(tags)  # "vip,superfan,member" or "superfan"
```

**Skript side** (`overlayStream.sk` /chatlog): Loops through `split arg-1 at ","` and builds prefix:

```skript
command /chatlog <text> [<text>] <player> [<text>]:
    trigger:
        set {_prefix} to ""
        loop split arg-1 at ",":
            if loop-value is "vip":        set {_prefix} to "%{_prefix}%&7[&aVIP&7]"
            else if loop-value is "superfan": set {_prefix} to "%{_prefix}%&7[&5SuperFan&7]"
            else if loop-value is "member":  set {_prefix} to "%{_prefix}%&7[&6Member&7]"
            else if loop-value is "friend":  set {_prefix} to "%{_prefix}%&7[&eFriend&7]"
            else if loop-value is "follower": set {_prefix} to "%{_prefix}%&7[&9Follower&7]"
            else if loop-value is "newbie":  set {_prefix} to "%{_prefix}%&7[&7Newbie&7]"
            else if loop-value is "follow":  send "&7[&9Follow&7] &c%arg-2% &fhas &9followed" to arg-3; stop
            else if loop-value is "share":   send "&7[&4Share&7]&c[%arg-2%]&7: &f%arg-4%" to arg-3; stop
        send "%{_prefix}%&7[%arg-2%]&7: &f%arg-4%" to arg-3
```

Colors: VIP=&a, SuperFan=&5, Member=&6, Friend=&e, Follower=&9, Newbie=&7. Follow and share use their own display format with `stop`.

## JSON Log Persistence Pattern

All event data (gifts, follows, chat) is persisted to JSON files using the same thread-safe pattern. This enables post-stream report generation.

### Log Files

| File | Content | Rolling Cap | Written By |
|------|---------|-------------|------------|
| `gift_log.json` | Gift events (sender, name, coins, tier) | 200 | `append_gift_log()` |
| `follow_log.json` | New followers (nick, unique_id, avatar) | 100 | `append_follow_log()` |
| `chat_log.json` | Chat messages (nick, comment, badge tags) | 500 | `append_chat_log()` |
| `stream_state.json` | Session metadata (room_id, start time, username) | 1 | `on_connect` handler |

### Thread-Safe Append Pattern

All `append_*` functions share the same structure:

```python
import threading as _threading
_log_lock = _threading.Lock()

def append_chat_log(nick, unique_id, comment, tags):
    """Log chat messages to chat_log.json for post-stream reports."""
    with _log_lock:
        log_file = "chat_log.json"
        entries = []
        if os.path.exists(log_file):
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    entries = json.load(f)
            except (json.JSONDecodeError, IOError):
                entries = []
        entries.append({
            "nick": nick,
            "unique_id": unique_id,
            "comment": comment,
            "tags": tags,  # e.g. "vip,superfan,member"
            "timestamp": time.monotonic()
        })
        entries = entries[-500:]  # rolling window
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
```

Same pattern for `append_gift_log` and `append_follow_log`. The `_log_lock` prevents race conditions when multiple event coroutines write simultaneously.

### Stream State Tracking

On connect, write `stream_state.json` with session metadata for report grouping:

```python
@client.on(ConnectEvent)
async def on_connect(event: ConnectEvent):
    # Clear logs for fresh session
    for log_file in ["gift_log.json", "follow_log.json", "chat_log.json"]:
        try:
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump([], f)
        except Exception:
            pass

    # Write stream state for report generation
    stream_state = {
        "room_id": client.room_id,
        "started_at": datetime.datetime.now().isoformat(),
        "username": event.unique_id
    }
    with open("stream_state.json", "w", encoding="utf-8") as f:
        json.dump(stream_state, f, indent=2)
```

**Why clear on connect:** Each live has a different `room_id`. Clearing ensures reports don't mix data from previous streams. The `stream_state.json` records the room_id so reports can be grouped/identified.

### Chat Log Hook (in on_comment)

After tag computation, before `log_and_send()`:

```python
tag_str = ",".join(tags)
append_chat_log(nick, uid, event.comment or "", tag_str)  # NEW
await log_and_send(tag_str, gifter_level, nick, comment)
```

### Post-Stream Report Generation

In the dashboard's `stop_bot()` function, after `bot_process.wait()`:

```python
def generate_report():
    """Generate a post-stream report from all log files."""
    # Reads: stream_state.json, gift_log.json, follow_log.json, chat_log.json
    # Computes: total coins, top 10 gifters, gift breakdown, unique chatters
    # Output: reports/stream_YYYY-MM-DD_HHMM_roomid.txt
    ...
```

Report sections: Stream info, Summary stats, Top gifters leaderboard, Gift breakdown, New followers, Full chat history with badge tags.

### .gitignore additions

```
chat_log.json
stream_state.json
reports/
```

### Pitfalls

- **`time.monotonic()` timestamps are relative to process start**, not absolute. For display in reports, the report generator uses `datetime.datetime.now()` for the generation time, and `stream_state.json` stores the ISO start time. Individual event timestamps are useful for ordering within a session, not for absolute time display.
- **Clearing logs on reconnect was destructive — fixed with room_id check.** Before 2026-05-26, `on_connect` cleared all logs unconditionally. A network blip mid-stream would wipe gift data, follow records, and chat history. **Fix:** compare `client.room_id` against `stream_state.json`. If same room_id → reconnect → preserve all logs. If different or no file → fresh stream → clear normally. See "Bot Reconnection & Resilience" section. This also means the bot can now auto-reconnect without data loss — the `run_bot()` reconnect loop handles the retry, and the `is_reconnect` check preserves the session.
- **⛔ PyInstaller `__file__` resolves to `_internal/`, not project root.** In a PyInstaller-frozen exe, `os.path.dirname(os.path.abspath(__file__))` resolves to `dist/TikTokMCIntegrator/_internal/`, NOT the directory containing the exe. The module-level `BASE_DIR` uses `sys.executable` when frozen (correct), but if any function creates its own local `BASE_DIR = os.path.dirname(os.path.abspath(__file__))`, it shadows the module-level one and writes to the wrong directory. **Fix:** Never re-declare `BASE_DIR` inside functions — always use the module-level one.

## Pitfalls

- **⛔ No reconnect loop = bot dies on any disconnect:** `run_bot()` was a single-shot `client.run()` call. If the WebSocket dropped mid-stream (network blip, TikTok server kick), the bot subprocess died and the user had to manually restart from the dashboard. **Fix:** wrap `client.run()` in a `while True` with exception-based differentiation — clean return = stream ended (break), exception = network issue (retry after 5s delay). See "Bot Reconnection & Resilience" section above.
- **⛔ Reconnect wipes all stream data:** `on_connect` clears gift_log, follow_log, chat_log unconditionally. On reconnect to the same stream, all pre-bliip session data is lost. **Fix:** compare `client.room_id` against `stream_state.json` before wiping. Same room_id → reconnect → preserve. Different or no file → fresh → clear. See "Bot Reconnection & Resilience" section.
- **⛔ WRONG PYTHON VERSION CHECK:** A bare `pip show TikTokLive` may hit a different interpreter than the project's. Always check `C:\Python313\python.exe -m pip show TikTokLive` before touching code.
- **⛔ String subscriptions crash:** `@client.on("barrage")` throws `AttributeError: 'str' object has no attribute 'get_type'`. v7's `on()` expects event classes, not strings. Use `@client.on(BarrageEvent)` or the specific subclass.
- **Run the project interpreter directly:** `C:\Python313\python.exe -m pip ...` — you run on Windows alongside the project, so install and verify there yourself.
- **Serial patches can mangle files:** When upgrading multiple sections of a file, write the complete final version rather than chaining many small find/replace edits. If one patch fails or matches incorrectly, the file is left in an inconsistent state and subsequent patches may fail or corrupt further. Restore from backup and rewrite cleanly.
- **`subprocess.terminate()` may skip `DisconnectEvent`:** When the dashboard's Stop button kills the bot subprocess via `terminate()`, the bot's asyncio event loop may never fire `DisconnectEvent`. Any cleanup in `on_disconnect` (e.g. zeroing `viewer_stats.json`) may not run. **Fix:** perform the same state cleanup from the parent process (Flask `stop_bot()`) AFTER `wait()` returns. Write zeros to shared state files directly from the dashboard side — don't rely on the child process's disconnect handler for forced stops.
- **⛔ Flask `debug=True` hides caught 500 JSON responses** — When Flask runs with `debug=True`, any exception in a request handler causes Flask to replace the response body with an HTML debug error page, **even if your try/except already caught the exception and returned `jsonify({...}), 500`**. The frontend receives HTML instead of JSON → `resp.json()` crashes → error invisible to dashboard. **Fix:** return 200 instead of 500 from caught exceptions (`return jsonify({"status":"error"...}), 200`), or run with `debug=False`. During debugging, always fetch with `.then(r => r.text())` first to see the raw body before relying on `.json()`.
- **⛔ Missing scoped imports = silent NameError** — When a function uses a module (e.g. `time.time()`) but that module was only imported inside a different function's scope, the current function gets `NameError`. Even if the module is imported at module level in other project files, each function needs its own import. TTS endpoint hit this with `time` — only imported in a different function via `import time; time.sleep(0.05)`, so `_tts_speak_impl()` had no `time` in scope. **Fix:** check every function's imports independently — don't assume a module imported elsewhere in the file is available.
- **⛔ Frontend fetch success ≠ API success** — `await fetch(url, {...})` resolves on ALL HTTP status codes (200, 400, 500). It only rejects on network errors. Dashboard code that shows success toasts after bare `await fetch()` will show "Success!" even on 500 errors. **Fix:** always check `response.ok` or inspect `response.status` before showing success feedback, especially for test/preview buttons.
- **Floating panels for real-time data:** When a panel shows live data (streaks, notifications) and appears/disappears frequently, use `position: fixed` instead of normal document flow. Normal flow causes layout shifts that annoy users when they're trying to read other content. Add a close button and remember dismissal state.
- **Stale real-time data cleanup:** When tracking real-time state (gift streaks, live counters), always add a `last_updated` timestamp. Auto-remove entries older than a threshold (e.g., 30 seconds) on each save. This prevents "stuck" state when the end signal never arrives (disconnect, network issue).
- **Overlay progress bar: drift detection against local timer causes periodic jumps** — An earlier version compared server `progress_ms` against the local timer's `getSongProgressNow()` estimate for drift detection. Every cache refresh caused a micro-jump as the local timer ran slightly ahead, then snapped back to stale data. The fix: track `lastSyncedProgressMs` (the last server position you actually accepted) and only detect jumps by comparing new server data against that. Never compare server data against a locally-interpolated estimate for sync decisions. See `references/song-overlay-progress-sync.md`.
- **Overlay progress bar: `cardWasHidden` must be captured BEFORE modifying `display`** — Checking `card.style.display === 'none'` after setting `card.style.display = ''` always returns false. Capture `const cardWasHidden = card.style.display === 'none'` before any DOM mutation, then use that captured value for force-sync logic. Without this, pause→resume never re-syncs and the bar jumps back to the frozen pause position. When an overlay (top gift, top streak) finds the current top value from a data array via `.reduce()`, using `val > maxVal` (strict greater) means ties always keep the FIRST entry in the array. Newer entries with the same value never display. Fix: use `val >= maxVal` so the latest entry to match the max value wins. Applies to both `handleTopGift` and `handleTopStreak` in `templates/overlay.html`. This was a live-stream bug — user saw the same top gifter all stream even though another viewer tied the value later.
- **⛔ JS duplicate `const` in overlay handlers = silent total failure** — Declaring `const upcoming = ...` twice in the same `handleSong()` scope throws a parse-time `SyntaxError` that kills the entire function before it ever runs. The overlay shows nothing, no errors in console (unless DevTools is already open). Always grep for duplicate `const`/`let` declarations after any copy-paste refactor in `templates/overlay.html`. See `systematic-debugging` skill for full diagnosis steps.
- **⛔ STATIC FILES AND PROFILES HAVE TWO COPIES:** When modifying frontend files (`static/script.js`, CSS, `templates/index.html`) or profiles (`profiles/*.yml`), you MUST update BOTH `source/` AND `release/TikTokMCIntegrator/_internal/`. The release copy gets bundled into the PyInstaller exe. If you only update one, the user sees stale UI or wrong gift config until they rebuild. Backend changes (`app.py`) only need one edit since it's compiled into the exe.

### Release Sync Without Rebuild

When the user has frontend/config changes that need to go to the release folder but **doesn't want to rebuild** (because the release has custom config, profiles, or runtime data they don't want to overwrite):

**Standard sync (templates + static + profiles — always safe):**
```bash
cp <source>/templates/index.html                       <release>/_internal/templates/index.html
cp <source>/static/script.js                             <release>/_internal/static/script.js
cp <source>/static/style.css                             <release>/_internal/static/style.css
cp <source>/profiles/*.yml                               <release>/_internal/profiles/
```

**⚠️ Windows case-insensitivity trap on D:\:** The D: drive (NTFS) is case-insensitive by default. `survival.yml` and `Survival.yml` are the SAME file. `cp` to an existing uppercase file may create a second lowercase copy, or `rm` may delete both. Always verify with `diff` after every profile copy. If the release has a filename with different case than source, match the release's case exactly — or standardize with `ls` first, then use that case for all future operations.

**What NOT to copy from source to release:**
- `config.yml` — release has live config
- `app.py` — is compiled into the .exe, copying it does nothing
- `available_gifts.json` — release has live gift cache
- Any runtime JSON file (gift_log, follow_log, stream_state, song_blocked_uris, song_queue, etc.)

**Verification:** After sync, check the release copy has the new feature:
```bash
grep "NEW_FEATURE_MARKER" <release>/_internal/templates/index.html
grep "newFunctionName"    <release>/_internal/static/script.js
diff profiles/<name>.yml   <release>/_internal/profiles/<name>.yml
```

**When to rebuild instead:** Only when `app.py` (backend Python) changes, or when new Python dependencies are added. Frontend-only changes (HTML, JS, CSS, static assets, YAML profiles) can always be hot-synced to `_internal/`.

### Full Rebuild & Release Deployment (CRITICAL — read before every rebuild)

**⛔ CRITICAL: Current release structure puts everything at `release/` ROOT, NOT in a subfolder.**

The old structure (pre-2026-05-27) had the exe at `release/TikTokMCIntegrator/TikTokMCIntegrator.exe`. The current structure (post-2026-05-27 cleanup) is:

```
release/
  TikTokMCIntegrator.exe   ← new build
  _internal/                ← new build DLLs + templates
  config.yml               ← LIVE runtime config
  profiles/                 ← LIVE profile YAMLs
  song_spotify_token.json   ← LIVE Spotify OAuth
  ... (all log files, cache, runtime state)
```

After `PyInstaller` produces `dist/TikTokMCIntegrator/`, deploy to the release folder **without destroying runtime configs**:

```bash
# ⛔ NEVER: rm -rf release/ && cp -a dist/TikTokMCIntegrator/ release/
# This wipes config.yml, profiles/, song_spotify_token.json, all runtime data.

# ⚠️ FIRST: Check for old nested subfolder (pre-2026-05-27 layout)
if [ -d "release/TikTokMCIntegrator" ]; then
    # Move ALL runtime data files UP from the old subfolder to release/ root
    for item in release/TikTokMCIntegrator/*; do
        name=$(basename "$item")
        if [ "$name" != "TikTokMCIntegrator.exe" ] && [ "$name" != "_internal" ]; then
            rm -rf "release/$name" 2>/dev/null
            mv "$item" "release/$name"
        fi
    done
    rm -rf release/TikTokMCIntegrator
    echo "Migrated data from old TikTokMCIntegrator/ subfolder"
fi

# ✅ CORRECT: Copy only the build artifacts, preserving runtime files
cp dist/TikTokMCIntegrator/TikTokMCIntegrator.exe release/
cp -r dist/TikTokMCIntegrator/_internal release/
```

**What the release folder contains (DON'T DELETE THESE):**
- `config.yml` — LIVE gift config, RCON credentials, VIP list, event bindings
- `profiles/` — profile YAML files
- `song_config.json` — Spotify commands, permissions, credentials
- `song_spotify_token.json` — Spotify OAuth token (reconnect if lost)
- `song_queue.json`, `song_history.json`, `song_blocked_uris.json` — song request runtime state
- `gift_log.json`, `follow_log.json`, `chat_log.json` — event logs
- `stream_state.json` — current stream metadata
- `available_gifts.json` — cached gift catalog

**After deploying, verify runtime configs survived:**
```bash
ls -la release/config.yml
ls -la release/profiles/
ls -la release/song_config.json
ls -la release/song_spotify_token.json
```
If any are missing, restore from the pre-build backup immediately.

**Pitfall — duplicate exe confusion:** The old pattern (exe inside `release/TikTokMCIntegrator/`) left a SECOND exe at release/TikTokMCIntegrator/TikTokMCIntegrator.exe. If you also copy to release/ root, there are TWO exes with DIFFERENT build dates. The user doesn't know which to run. **Fix:** Always check for and clean up the old `release/TikTokMCIntegrator/` subfolder before copying the new build. See the migration block above.

- **⛔ Windows Defender locks dist/ folder:** After a build, Defender Real-Time Protection holds a file handle on `dist/TikTokMCIntegrator/`. Next build fails with "file is being used by another process" even though the folder looks empty. Explorer restart does NOT fix this (it's a kernel service lock, not a shell extension). **Fix:** Add `dist/` to Defender exclusions permanently, or update build.bat to rename the locked folder instead of deleting it. See `references/pyinstaller-defender-lock.md` for the full fallback script and diagnosis steps.

### Tray Exit Confirmation (Windows Dialog)

When closing the system-tray app while the bot is running, show a Windows-native dialog with 3 options to prevent accidental shutdown mid-stream. Uses `tkinter.messagebox.askyesnocancel` (Yes/No/Cancel):

- **Yes** → Stop bot, generate report, close
- **No** → Close app, leave bot running in background
- **Cancel** → Keep everything running (no-op)

Pattern in `main.py`:

```python
def exit_app(icon, item):
    try:
        from app import bot_process
        import app as app_module
        bot_running = (app_module.bot_process is not None
                       and app_module.bot_process.poll() is None)
    except Exception:
        bot_running = False

    if bot_running:
        import tkinter.messagebox
        root = tkinter.Tk()
        root.withdraw()
        result = tkinter.messagebox.askyesnocancel(
            "Bot Still Running",
            "The TikTok bot is still connected.\n\n"
            "Yes  → Stop bot & close\n"
            "No   → Close without stopping (bot runs)\n"
            "Cancel → Keep the app open"
        )
        root.destroy()

        if result is None:   return  # Cancel
        if result:  # Yes — stop bot
            bot_process.terminate()
            bot_process.wait()
            bot_process = None
            generate_report()

    icon.stop()
    os._exit(0)
```

**Pitfall:** `root.withdraw()` prevents a tkinter window from flashing, but the hidden root must be `root.destroy()`'d or the app won't fully exit. Only shows when the bot is running; just exits silently otherwise.

- **TYPE_CHECKING blocks:** v7 events declare fields under `if TYPE_CHECKING:` — these are type hints only. The actual fields come from the inherited proto message class. Check both.
- **`event.user` is a raw `User` proto at runtime:** v7 alpha never converts `event.user` to `ExtendedUser` automatically. The type annotation says `ExtendedUser` but the actual object is a raw proto `User`. All ExtendedUser convenience properties (`member_level`, `gifter_level`, `is_moderator`, `is_top_gifter`, `is_friend`, `unique_id`) are unavailable unless you convert first. **Fix:** `from TikTokLive.proto.custom_proto import ExtendedUser` then `u = ExtendedUser.from_user(event.user) if event.user else None`. Do this early in any handler that needs badge-based properties. Proto fields (`nickname`, `badge_list`, `follow_info`, `avatar_thumb`) work directly without conversion.
- **Dependencies on install:** v7 requires `TikTokLiveProto` (auto-installed), `betterproto2`, `mashumaro`, `protobuf3-to-dict`. If install fails, check these are all resolved.

## Profile YAML Config Structure

**⛔ NEVER modify profile .yml files unless explicitly asked.** The user has custom configs in their release folder that may differ from what's in the repo. When asked to "fix" something, clarify if they want the profile changed or if the issue is in the Python code.

Profiles (`profiles/<name>.yml`) define gift-to-Minecraft-command mappings. The active profile is stored in `active_profile.txt` and gets copied to `config.yml` on switch.

### Sections

| Section | Purpose | Example |
|---------|---------|---------|
| `Gifts` | Gift ID → list of RCON commands | `'5585': - tnt {mc} nuclear {amount} {user}` |
| `GiftCategories` | Gift ID → coin tier display | `'5585': 100 Coins` |
| `GiftNames` | Gift ID → display name | `'5585': confetti` |
| `StreakDeltaGifts` | Gift IDs that use streak-delta mode | `- '5827'` |
| `Events` | Non-gift events (Follow, Comment, Like, SuperFan) | See hot-reload section |
| `GlobalActions` | Commands fired on EVERY gift (chat logging, scoreboard) | See GlobalActions section |
| `Rcon`, `Settings`, `VIP_List` | Server connection + user config | Standard |

### Gift Key Types

Keys can be either **numeric gift IDs** (e.g. `'5585'`) or **name strings** (e.g. `nasi lemak`). Name keys serve as fallback when the TikTok gift ID doesn't exist in the current catalog. Both work at runtime.

### Finding the Correct RCON Commands

**NEVER guess the RCON commands.** The actual command syntax lives in the Skript files at `D:\Ikhito\Code\minecraftSkript\`. Each Skript file corresponds to a gift category:

| Skript File | Command Pattern | Entity/Types |
|-------------|----------------|--------------|
| `tiktokItems.sk` | `giveitem {mc} <item_key> {amount} {user}` | ender_pearl, golden_apple, totem_of_undying, cooked_beef, iron_ingot |
| `tiktokSpawn.sk` | `spawnmob {mc} {amount} <entity_key> {user}` | husk (baby), creeper, blaze, witch, cave_spider, pillager, skeleton (armored), warden, evoker, vindicator, ravager |
| `tiktokSpawn.sk` | `randommob {mc} {amount} {user}` | Weighted pool (zombie, skeleton, cave_spider, creeper, etc.) |
| `tiktokTNT.sk` | `tnt {mc} <tnt_key> {amount} {user} [resist_secs]` | nuclear, firework, honey, meteor, wither_storm, lightning_storm, lava_ocean, death_ray, tnt_rain, disintegrating, fire, catalyst, acidic |
| `tiktokUnique.sk` | Various per-command | creative, levitate, pumpkinhead, netheriteset, meteorshower, worldeater, clearinven, rtp, cobwebtrap |

**Mandatory workflow when importing a gift list from Obsidian:**
1. Read the Obsidian note — it tells you which Skript file + entity each gift maps to
2. Read the actual `.sk` file from `D:\Ikhito\Code\minecraftSkript\` to get the exact command syntax
3. Map gift IDs that still exist in `available_gifts.json` — those get numeric keys in Gifts/GiftCategories/GiftNames
4. For gifts where the Obsidian ID doesn't match the current catalog, use **name-based keys** and note the coin value for future substitution
5. Sync BOTH `profiles/<name>.yml` and `release/TikTokMCIntegrator/profiles/<name>.yml` after any change

### Verifying a New Profile

```bash
# Check YAML validity and structure
python3 -c "
import yaml
with open('profiles/<name>.yml') as f:
    data = yaml.safe_load(f)
print(f'Gifts: {len(data.get(\"Gifts\",{}))} entries')
print(f'GiftCategories: {len(data.get(\"GiftCategories\",{}))} entries')
print(f'GiftNames: {len(data.get(\"GiftNames\",{}))} entries')
"

# Verify source and release are in sync
diff profiles/<name>.yml release/TikTokMCIntegrator/profiles/<name>.yml
```

### Adding GiftNames Entries

Each gift used as a numeric ID key should also have a `GiftNames` entry so the dashboard and overlays display the correct name. Name-based keys should also get a GiftNames entry with the same key-value pair.

## When to Graphify (and When Not To)

See `references/refactoring-plan.md` for the full codebase analysis and phased refactoring plan (3,900 lines, 189 functions, 29 silent errors, 38 duplicate JSON patterns).

Graphify builds knowledge graphs from codebases. It's valuable for YOUR code (tracking complexity, finding god nodes, community structure). But for external libraries:

**Skip graphing the library source if:**
- You already have deep practical knowledge from debugging it (field renames, broken methods, workarounds)
- Your skill docs already capture the important patterns and pitfalls
- The library is actively being updated (graph goes stale fast)
- You're using it, not contributing to it

**Graph the library source if:**
- You're planning to contribute upstream or fork it
- You need to understand a part of the API you haven't touched yet
- The library is large and complex with many interconnected modules

For TikTokLive specifically: the bug-hunt session (5 bugs, field renames, ExtendedUser vs raw proto, badge struct v3) gave deeper practical knowledge than a graph would. The `tiktok-live-bot-dev` skill captures all of it. Graphing the library source was correctly cancelled (2026-05-01).

## Spotify Song Requests Pattern

Design ref: `references/song-requests-spotify.md`. Queue arch: `references/song-queue-architecture.md`.

## Deployment

Two communication paths:
- **Flask app** (`app.py`) — manages OAuth flow, config CRUD, queue/history API, overlay data endpoint `/api/stats/song`
- **Bot subprocess** (`minecraftDiamond.py`) — reads `song_config.json`, listens for chat commands in `on_comment`, calls Spotify API for search/queue/skip, writes to `song_queue.json` and `song_history.json`
- **Shared module** (`spotify_handler.py`) — both processes import this for token management, Spotify API calls, and queue operations. Must have the same `BASE_DIR` resolution pattern (`sys.executable` when frozen).

### Key Design Decisions

1. **Local queue first, not direct Spotify push** — Spotify's API can add to queue but cannot remove arbitrary queued tracks. Store pending requests in `song_queue.json`. Only push to Spotify when actually ready to play (or when nothing is currently playing and a request comes in). This enables `!revoke`, per-user limits, dashboard remove/clear, and reliable history.

2. **Rate limit defense** — 3s playback cache + global cooldown (`_rate_limit_until`) stops ALL API calls during a 429 ban. The overlay uses local timer interpolation between polls for smooth progress bars. See `references/song-overlay-progress-sync.md`.

2. **Editable commands** — Store `play_command`, `skip_command`, `revoke_command` in `song_config.json`. The bot's `on_comment` handler must normalize command detection:
   ```python
   comment_lower = comment.strip().lower()
   if comment_lower.startswith(play_cmd + " ") or comment_lower == play_cmd:
       query = comment[len(play_cmd):].strip()
   ```

3. **Per-command permissions** — Each command has its own permission block with OR-condition category checks plus a specific TikTok `unique_id` whitelist. Categories checked against the user's computed tag hierarchy (`vip`, `superfan`, `member`, `friend`, `follower`). Must also expose `is_moderator` from ExtendedUser for `!skip`.
   ```python
   user_info = {
       "unique_id": uid,
       "is_vip": is_vip,
       "is_superfan": is_superfan,
       "is_member": is_member,
       "is_friend": is_friend,
       "is_follower": is_follower,
       "is_mod": getattr(u, 'is_moderator', False) if u else False,
   }
   ```

4. **Spotify OAuth flow for a local app** — Use popup window + `postMessage` callback pattern:
   - User clicks "Connect" → dashboard fetches auth URL from Flask → opens popup
   - User authorizes in Spotify popup → redirects to Flask `/api/spotify/callback`
   - Callback exchanges code for token, returns HTML that calls `window.opener.postMessage`
   - Dashboard listens for message and updates status

### Spotify Endpoints Used

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/me/player/queue?uri=` | POST | Queue a track to active device |
| `/me/player/next` | POST | Skip current track |
| `/me/player` | GET | Get current playback state |
| `/me/player/devices` | GET | List available devices |
| `/search?q=&type=track&limit=` | GET | Search for tracks |
| `/me/player` | PUT | Transfer playback to device |

Scopes required: `user-read-playback-state`, `user-modify-playback-state`, `user-read-currently-playing`. Spotify Premium is required.

### Runtime Files

| File | Purpose |
|------|---------|
| `song_config.json` | Editable commands, permissions, Spotify credentials, queue limits |
| `song_queue.json` | Pending requests with status (queued/playing/played/skipped) |
| `song_history.json` | Completed/skipped tracks |
| `song_spotify_token.json` | OAuth token with refresh |
| `song_blocked_uris.json` | Blocked URIs of revoked pushed songs (auto-skipped by worker) |

### Permission Config Shape

```json
{
  "play_permission": {
    "everyone": true,
    "followers": false,
    "friends": false,
    "superfans": false,
    "vip": false,
    "whitelist": []
  },
  "skip_permission": {
    "mods": true,
    "vip": true,
    "superfans": false,
    "members": false,
    "whitelist": ["ikhito"]
  }
}
```

### Dashboard Song Tab

Build the Song panel as a finished dashboard, not raw form scaffolding. User reacted strongly against a full-width, tiny-control, plain stacked form UI; treat UI quality as part of the feature.

Preferred structure:
1. **Spotify hero/header** — status badge, active device, connect/disconnect buttons, short explanation.
2. **Main column** — Commands & Spotify credentials, Song Queue, Test Search.
3. **Side column** — Permissions and History.
4. **Commands strip** — compact editable `!play`, `!skip`, `!revoke` fields grouped together.
5. **Reusable row cards** — queue/history/search rows with album art, title, subtitle, status/action.
6. **Styled empty states** — small icon/text cards, not plain centered text.

Use class-based CSS for the Song tab. Avoid lots of inline styles, full-width ungrouped forms, default white inputs, tiny labels floating in empty space, and especially big unused gaps between columns. Cards should fill their columns neatly; if the layout creates a middle canyon, rebalance/extend the grid before shipping. Spotify green (`#1ed760`) is appropriate as a subtle accent while keeping the app's dark dashboard theme.

Permissions UI should stay symmetric: expose the same categories for `!play` and `!skip` (Everyone, Followers, Friends, SuperFans, Members, Moderators, VIP, Whitelist), while keeping strict defaults for `!skip`.

See `references/song-ui-build-pitfalls.md` for concrete UI and build lessons from the Song Requests implementation.

### Song Overlay

Compact corner-friendly `/overlay/song` browser source (~340px wide):
- NOW PLAYING section with album art, title, artist, animated progress bar (Spotify-green)
- UP NEXT section with divider showing next track + requester
- Hidden when no data
- Glass card style matching the existing top gift/top streak overlays
- Glass card style matching the existing top gift/top streak overlays
- **Progress bar sync — see `references/song-overlay-progress-sync.md`**: backend caches Spotify at 2s, overlay polls backend every 1s, but the bar ticks locally at 250ms. Only re-syncs on four events: track change, play/pause state flip, card re-appearing after hidden pause, and seek/jump detected via `lastSyncedProgressMs` (>5s change from last accepted server position). Comparing against the local timer estimate causes periodic jumps — always compare server positions against `lastSyncedProgressMs` instead. This prevents freeze, fast-forward desync, pause/resume jump-back, and repeat-same-track stuck-at-end bugs. **Class-level reusable skill: `media-progress-overlay`** — for any media player overlay, not just Spotify.

#### Queue Integrity (Duplicate Prevention + Active-Only Limits)

Two related queue guardrails in `add_to_queue()`:

**Duplicate song detection** — Before adding, check if the same `spotify_uri` already exists in the queue with any active status (`queued`, `pushed`, `playing`). If found, reject with `"That song is already in the queue!"`. This prevents two viewers from stacking the same track.

```python
new_uri = track.get("uri", "")
if new_uri:
    for q in queue:
        if q.get("spotify_uri") == new_uri and q.get("status") in ("queued", "pushed", "playing"):
            return {"error": "That song is already in the queue!"}
```

**Active-only queue counting** — `max_queue_total` and `max_queue_per_user` must count only entries with status `queued`, `pushed`, or `playing`. Songs that finished (`played`) or were skipped should not consume queue slots. This way, as songs finish and leave the overlay, they free up capacity for new requests — the pool stays full at `max_queue_total` active entries.

```python
active_count = sum(1 for q in queue if q.get("status") in ("queued", "pushed", "playing"))
if active_count >= max_total:
    return {"error": f"Queue is full (max {max_total} active). Try again later."}
```

The same `active_count` filter applies to per-user limits. Without this, the queue fills up permanently after `max_queue_total` total requests and never accepts new songs.

#### On_comment Flow Order (Chat Before Song Processing)

**Critical ordering constraint in `minecraftDiamond.py`'s `on_comment`:** song command handlers (`!play`, `!skip`, `!revoke`) have early `return` statements. If `log_and_send()` (which sends the chat to Minecraft via `/chatlog` RCON) is placed AFTER the song command block, ALL song commands get swallowed — the viewer's message never appears in Minecraft or the overlay.

**Correct order:**
```python
tag_str = ",".join(tags)

# 1. Extract avatar + badges
avatar_url = ""
try:
    thumb = getattr(u, 'avatar_thumb', None) if u else None
    if thumb and getattr(thumb, 'url_list', None):
        avatar_url = thumb.url_list[0]
except Exception:
    pass
badges = _extract_badge_icons(u) if u else []

# 2. ALWAYS log and send to Minecraft FIRST (before song command processing)
append_chat_log(nick, uid, event.comment or "", tag_str, avatar_url, badges, gifter_level, member_level)
await log_and_send(tag_str, gifter_level, nick, comment)

# 3. THEN process song commands (they return early, but chat already went to MC)
if comment_lower.startswith(play_cmd + " ") or comment_lower == play_cmd:
    ...
    return  # safe — log_and_send already called above
```

**Without this ordering,** viewers type `!play some song` and it never appears in Minecraft chat. The only response is the `tell` confirmation. The user wants song commands to act like regular chat — visible in the Minecraft feed with badge tags.

**Pitfall:** The chat filter (CHAT_FILTER, CHAT_FILTER_MIN_GIFTER_LEVEL, CHAT_FILTER_MIN_MEMBER_LEVEL) runs AFTER song command processing. Since `log_and_send` is now called before the filter, ALL messages (including filtered ones) go to Minecraft. This is intentional — the user wants to see everything. Song command permission denials still block the command response (`tell`), but the original chat message is already visible.

#### Upcoming List Data Contract

The overlay's "UP NEXT" section must show **all upcoming songs**, not just the next single track. The backend endpoint should return an `upcoming` array containing every queue entry with status `"queued"` or `"pushed"` (anything not yet playing or played).

**Backend (`app.py`):**
```python
@app.route("/api/stats/song")
def get_song_stats():
    queue = load_queue()  # from spotify_handler
    upcoming = [
        {
            "name": entry.get("track_name", "Unknown"),
            "artist": entry.get("artist", ""),
            "requested_by": entry.get("requested_by", ""),
        }
        for entry in queue
        if entry.get("status") in ("queued", "pushed")
    ]
    return jsonify({
        "now_playing": { ... },
        "upcoming": upcoming,  # ALL pending songs, not just [0]
    })
```

**Frontend (`overlay.html`):**
```javascript
function renderSongOverlay(data) {
    // ... now playing section ...

    // Upcoming list — render ALL items, not just data.upcoming[0]
    const upcomingContainer = document.getElementById('song-upcoming');
    if (data.upcoming && data.upcoming.length > 0) {
        upcomingContainer.innerHTML = data.upcoming.map((song, i) => `
            <div class="song-upcoming-item">
                <span class="song-number">${i + 1}</span>
                <div class="song-upcoming-info">
                    <div class="song-upcoming-name">${escHtml(song.name)}</div>
                    <div class="song-upcoming-artist">${escHtml(song.artist)} · ${escHtml(song.requested_by)}</div>
                </div>
            </div>
        `).join('');
        upcomingContainer.style.display = '';
    } else {
        upcomingContainer.style.display = 'none';
    }
}
```

**Pitfall:** Returning only the first upcoming item (`upcoming = queue[0] if queue else None`) means viewers never see the full queue depth. The overlay looks empty or misleading when multiple people have requested songs. Always return the full array and let the frontend decide how many to render.

#### Overlay Instant Sync (Live URI Cross-Reference)

The overlay's `/api/stats/song` endpoint historically relied **solely** on the worker's status flag (`"playing"`) to determine `now_playing`. But the worker only polls every 3s (or 30s with push delay), so there's a gap where a song is actually playing on Spotify but still shows as `"pushed"` in the queue → it appears in `upcoming` instead of `now_playing`.

**Fix:** Cross-reference Spotify's actual playback URI against every queue entry's `spotify_uri`. If Spotify is playing a track whose URI matches any `"queued"` or `"pushed"` entry, treat it as `now_playing` and exclude it from `upcoming`. This makes the overlay update **instantly** when Spotify transitions to a new track, regardless of the worker's polling cycle. The worker eventually catches up and changes the status to `"playing"`, but the overlay doesn't wait for it.

Key code in `app.py`'s overlay endpoint:

```python
playback = sh.get_current_playback()
current_spotify_item = playback.get("item") if isinstance(playback.get("item"), dict) else None
current_spotify_uri = current_spotify_item.get("uri") if current_spotify_item else None

# now_playing: first by status, then by URI cross-reference
now_playing = None
for q in queue:
    if q.get("status") == "playing":
        now_playing = q
        break

if not now_playing and current_spotify_uri:
    for q in queue:
        if q.get("spotify_uri") == current_spotify_uri and q.get("status") in ("queued", "pushed"):
            now_playing = q
            break

# upcoming: exclude whatever we identified as now_playing
playing_uri = now_playing.get("spotify_uri") if now_playing else None
upcoming = [q for q in queue
            if q.get("status") in ("queued", "pushed") and q.get("spotify_uri") != playing_uri]
```

**Pitfall:** The `item` field from `get_current_playback()` can be `None` (nothing playing) or an error dict. Always check `isinstance(item, dict)` before accessing `uri` to avoid `NoneType.get()` errors.

#### Overlay Vertical Expansion (No Clipping)

The song card must **expand vertically** to fit all queued songs, not scroll up and clip the now-playing section. With a default `max_queue_total` of 10 and each "Up Next" item ~28px tall, the card needs ~350px of vertical space.

**The bug:** Both `.song-overlay-wrap` and `.song-card` had `overflow: hidden`. The card is `position: fixed; bottom: 16px;` — it grows upward from the bottom-right. When enough songs were queued, the card extended above the viewport edge. The now-playing section (at the top of the card's content flow) got pushed above the viewport and clipped by `overflow: hidden`. Users saw the card "scrolling up" with the now-playing and some queue items invisible.

**The fix — three CSS changes on `.song-card`:**

1. `overflow: visible` — never clip content within the card
2. `max-height: calc(100vh - 32px)` — prevent extension beyond viewport
3. `display: flex; flex-direction: column` — allow the upcoming list to shrink/scroll while the now-playing takes its natural height

Plus make the upcoming list itself scrollable:
```css
.song-upcoming-list {
  overflow-y: auto;
  max-height: 50vh;
  scrollbar-width: thin;
  scrollbar-color: rgba(255,255,255,0.12) transparent;
}
```

This way: the now-playing section stays pinned at the top of the card (always visible), and the upcoming list scrolls internally if it exceeds available space. The card naturally grows to fit all queued songs up to `max_queue_total`, then stops at the viewport limit and scrolls only the upcoming section.

### Context-Purge Revoke (X-Confirm-Patch)

Since Spotify has no API endpoint to remove a queued track, and the primary revoke path now uses context-purge (`references/spotify-context-purge.md`), this blocked-URI mechanism is the fallback. Three components:

**1. Persistent URI blocklist (`song_blocked_uris.json`)**
A thread-safe JSON file storing URIs of revoked songs that were already pushed to Spotify. Loaded and saved with exclusive file locks. Created on first revoke; does not exist until needed.

**2. Revoke hook in `remove_from_queue()`**
When removing an entry with `status == "pushed"`, save its `spotify_uri` to the blocklist BEFORE popping it from the queue. This captures the song before it disappears from the local queue.

```python
removed = queue.pop(position)
save_queue(queue)

if removed.get("status") == "pushed":
    uri = removed.get("spotify_uri", "")
    if uri:
        add_blocked_uri(uri)
```

**3. Worker auto-skip in `process_song_queue()`**
After the playback sync section, check if Spotify's `current_uri` is in the blocklist. If it is:
- Mark it as `"skipped"` in the local queue and add to history
- Call `skip_track()` (Spotify `/me/player/next`)
- Remove the URI from the blocklist

```python
# In the worker's main loop, after state_changed / before last_seen_uri
if current_uri:
    blocked = load_blocked_uris()
    if current_uri in blocked:
        # Mark in local queue
        for q in queue:
            if q.get("spotify_uri") == current_uri:
                q["status"] = "skipped"
                add_to_history(dict(q))
        save_queue(queue)
        # Skip on Spotify
        skip_result = skip_track()
        remove_blocked_uri(current_uri)
```

**Edge cases:**
- **Revoked song already playing** — `_purge_and_repush` detects and calls `skip_track()` immediately. Brief audible skip.
- **Multiple revoked songs** — Each revoke purges context and re-pushes remaining.
- **Only song revoked** — Context stays as `[current_uri]`. Loop song queued as fallback.
- **Purge fails** — Falls back to blocked-URI + 3s rapid-poll.
- **!skip after play_track_immediate** — Empty queue → handler checks playback → resumes loop song.
- **!skip with queued songs** — Already pushed by !play handler → works.

See `references/song-blocked-uris.md` for the full implementation reference.

### Pitfalls

- **⛔ spotify_handler imported from frozen subprocesses** — When `minecraftDiamond.py` imports `spotify_handler` and runs as a PyInstaller-frozen exe, `os.path.abspath(__file__)` resolves to `_internal/`, not the project root. The handler must use the same `BASE_DIR` detection pattern: `os.path.dirname(sys.executable)` when frozen.
- **⛔ Secret masking vs save** — When the dashboard GETs song config, mask the client secret as `"••••"`. The save logic must handle the case where the user submits the masked value back unchanged (don't overwrite with `"••••"`).
- **Token refresh race** — Both Flask and bot subprocess can try to refresh the token simultaneously. The token file operations use a thread lock, but between two processes, the last writer wins. Generally fine since both check expiry before refresh. **⛔ Without global cooldown this becomes a Spotify accounts-ban vector** — see `references/song-token-refresh-cooldown.md`.
- **Spotify must be playing something** — The queue endpoint only works when there's an active Spotify device with something playing (even silently). If nothing is playing, `queue_track` may silently fail or return an error.
- **No remove-from-Spotify-queue API** — Once a track is pushed to Spotify via `POST /me/player/queue`, it **cannot be removed** from Spotify's side. The fix is the **Blocked URIs Auto-Skip pattern**: save the revoked song's URI to `song_blocked_uris.json`, and the worker auto-skips it when Spotify starts playing it. This effectively makes the revoked song invisible on stream. See `references/song-blocked-uris.md` and the "Blocked URIs Auto-Skip" section above.
- **⛔ NEVER change user's Skript commands or profile configs without asking** — The user's Minecraft server has its own Skript commands in a SEPARATE server folder (not in the repo's `minecraftSkript/` directory). Commands like `tntspawn` ARE valid on their server even if not found in the repo. When debugging template substitution issues (like `{amount*50}`), focus ONLY on the Python app's `actions.py` — NOT on the Skript files or profile YAMLs. The user explicitly said: "NOT THE SKRIPT BUT THE APP" and "like i said don't touch the skript file man, it's different file". NEVER modify .sk files or profile .yml files unless the user explicitly asks you to.
- **⛔ Python TikTokLive lacks `sendMessage()` — and this is by design** — When investigating TikTok chat sending (auto-replies, gift acknowledgments), the Python library has no outbound capability. The original Node.js library (`zerodytrash/TikTok-Live-Connector` v2.1.1-beta1) had a working `sendMessage()` that POSTed directly to `webcast.tiktok.com/webcast/room/chat/` with Euler Stream signing + session cookie. Isaac Kogan deliberately removed this from both the Python port and the Node.js v7 rewrite. The v7 `sendMessage()` routes through `apiClient.premium.sendRoomChat()` — Euler Stream's paid proxy. The free sign API is deprecated. No zero-cost chat sending path exists. The only free alternative is browser automation (Playwright controlling a logged-in Chrome session typing into the DOM), which has 1-3s latency. See `references/euler-stream-premium-endpoints.md` for the full 4-round investigation.
- **Overlay upcoming list must return ALL pending songs** — If the `/api/stats/song` endpoint returns only a single `upcoming` object (the next track), the overlay shows just one item even when the queue has 5 requests. Viewers can't see queue depth and the feature feels broken. **Fix:** return `upcoming` as an array of every entry with status `"queued"` or `"pushed"`. The frontend maps over it and renders a numbered list. See the "Upcoming List Data Contract" subsection under Song Overlay above.
- **⛔ NEVER `rm -rf release/TikTokMCIntegrator`** — The release folder holds the user's LIVE runtime config (`config.yml`, `song_config.json`, `song_spotify_token.json`, `profiles/`, log JSONs). A full delete-and-replace destroys all of it. Prefer targeted file copies from `dist/` into `release/`, preserving all runtime files. If you do delete it, the source backup may have an outdated copy — the user's live edits are lost forever. This was violated on 2026-05-21 and caused config + profile loss requiring emergency backup extraction.
- **⛔ JS function name mismatch = silent blank UI** — If a helper like `esc()` is called but the actual function is named `escHtml()`, every call throws `ReferenceError`. In async handlers, this error is caught by the try/catch, which then also calls `esc()`, causing a second error. Result: the UI shows NOTHING — no results, no error text, not even a "Search failed" message. The `innerHTML` assignments fail before rendering. **Fix:** add `const esc = escHtml;` as an alias right after the function definition. See `references/js-silent-reference-error.md` for full diagnosis steps.
- **Token save silently fails after callback** — OAuth shows \"Connected!\" but no `song_spotify_token.json` is written. Add `print()` logging to `handle_callback` and `save_token` to surface the file path and write errors. Also log the callback route to confirm the `code` parameter arrived. See `references/song-ui-build-pitfalls.md` — Spotify token save section.\n- **Song queue needs a background worker** — The `!play` command adds to the local queue and pushes to Spotify only if nothing is currently playing. After the first song ends, remaining queued songs sit forever. **Fix:** add a daemon thread (`process_song_queue`) that polls playback every 3s, scans for `"queued"` items and pushes them immediately, and syncs playback state (`queued` → `pushed` → `playing` → `played`). Start it from `main.py` right after `ensure_profiles_setup()`. See `references/song-queue-worker.md` for the full fixed pattern.
- **⛔ Queue worker that only fires on `track_ended` is broken** — A worker that only pushes queued songs when `is_playing=False` or `item` is null means new requests sit idle while Spotify is actively playing. The correct pattern is to scan the local queue every few seconds and push ANY `"queued"` item immediately, regardless of current playback state. Use a `"pushed"` status to prevent double-push. Playback sync (detecting `playing` → `played`) should be a SEPARATE concern from the push logic, not the gate for pushing. See `references/song-queue-worker.md` for the corrected loop.
- **⛔ History won't auto-populate unless the worker calls `add_to_history()`** — When the queue worker detects a track ended and marks the local entry as `"played"`, that only updates `song_queue.json`. The history file (`song_history.json`) and the dashboard History tab stay empty. **Fix:** in the worker's playback-sync block where `status` changes from `"playing"` to `"played"`, immediately call `add_to_history(entry)` before `break`. See `references/song-queue-worker.md` for the exact placement.
- **⛔ History tab lacks auto-refresh polling in dashboard** — Even when the worker correctly calls `add_to_history()`, the dashboard frontend only calls `fetchSongHistory()` **once** on page load. There is no `setInterval(fetchSongHistory, ...)` polling, unlike every other dashboard section (queue polls every 2s, bot status every 3s). Users see empty history until they manually refresh the page. **Fix:** add `setInterval(fetchSongHistory, 3000)` in the `init()` function alongside the other interval fetchers.
- **⛔ Song commands swallow chat from Minecraft unless `log_and_send()` runs first** — `on_comment`'s `!play`/`!skip`/`!revoke` handlers all have early `return` statements. If `log_and_send()` is placed after them, the viewer's original message never appears in Minecraft. **Fix:** send to Minecraft (via `log_and_send`) BEFORE processing song commands. See "On_comment Flow Order" subsection.
- **⛔ `!revoke` is broken by the 3-second push window** — The queue worker scans every 3s and changes status from `"queued"` to `"pushed"` immediately. The `!revoke` handler in `minecraftDiamond.py` only finds entries with `status == "queued"`. Viewers have roughly 3 seconds after requesting to type `!revoke` — essentially impossible in practice. **Two fixes applied together: (a)** increased push delay from 3s to 30s (`time_mod.sleep(30)`) so viewers have a comfortable window to revoke before the song hits Spotify's queue. **(b)** For songs already pushed, use the **Blocked URIs Auto-Skip** pattern — save the revoked song's URI to a persistent blocklist (`song_blocked_uris.json`), and the worker auto-skips it when Spotify starts playing it. This handles the "can't remove from Spotify's queue" problem cleanly. See `references/song-blocked-uris.md` for the full pattern.
- **⛔ Dashboard queue renderer has no `"pushed"` status label** — `renderSongQueue()` in `static/script.js` defines status labels only for `playing`, `queued`, `played`, and `skipped`. Once the worker changes a song from `"queued"` to `"pushed"` (within ~3s), the dashboard shows the row with **empty status text** and the X button disappears (X only renders for `status === "queued"`). **Fix:** add `'pushed': '<span class="song-status-text"><i class="fa-solid fa-arrow-up"></i> Queued</span>'` to the `statusLabels` map, and extend the X-button condition to also include `"pushed"`.
- **⛔ Release vs source `song_config.json` divergence — command debugging trap** — The dashboard reads/writes the **release** copy of `song_config.json` (next to the EXE at `release/TikTokMCIntegrator/`). The **source project** copy (`D:\Ikhito\Code\TikTokMCIntegrator\song_config.json`) often has different command strings, permissions, or credentials because it is not synced automatically. When debugging why `!skip` or `!revoke` does not work in chat: always check the **release** copy — that is what the bot reads at runtime. This also applies to `song_queue.json` and `song_history.json` — the bot writes to release copies, not source copies.
- **⛔ Connection status false-positive (204 No Content = +Connected+ bug)** — Spotify's `/me/player` returns 204 No Content when there's no active device. `_spotify_get` silently returns `{}` for 204. Then `get_current_playback()` returns `{"is_playing": False}` with no error key. `get_connection_status()` sees no error → returns `connected: True`. Dashboard shows green dot — but the API rejects queue/skip calls. **Fix:** check `device_name` and `item` in `get_connection_status()`; if both empty, return `connected: False` with `"error": "No active Spotify device"`. Dashboard must surface `data.error` to the user instead of swallowing it. See `references/song-ui-build-pitfalls.md`.
- **⛔ OAuth popup errors are invisible to the dashboard** — When the Spotify callback (`/api/spotify/callback`) fails, the original code returned `jsonify(result), 400`, showing raw JSON text in the popup. The dashboard never sees it — no toast, no feedback. User closes popup confused. **Fix:** return HTML even on error, with `window.opener.postMessage({type: 'spotify-error', error: '...'}, '*')` plus `setTimeout(() => window.close(), 3000)`. Dashboard listens for `spotify-error` alongside `spotify-connected` and shows a red error toast. See `references/song-ui-build-pitfalls.md`.
- **Windows batch dependency versions must be quoted** — In `.bat`, `pip install spotipy>=2.24.0` can be parsed as output redirection because of `>`. Use `py -3 -m pip install "spotipy>=2.24.0" "requests>=2.28.0"`, and use the same Python command for `pip` and `PyInstaller`.
- **`.bat` files need Windows-safe formatting** — Write batch files as ASCII with CRLF line endings and avoid Unicode icons/checkmarks. Verify with `file build.bat` showing `DOS batch file, ASCII text, with CRLF line terminators`.
- **⛔ Token refresh must have global cooldown across all callers** — Without a `_token_refresh_until` cooldown, every poll cycle hits `accounts.spotify.com/api/token` independently when the token is expired or refresh fails. Dashboard (3s), worker (30s), and overlay (1s) together hammer >30 req/min. Spotify's accounts endpoint bans are **400x harsher** than data API bans (hours vs seconds). **Fix:** Gate `get_valid_token()` with `_token_refresh_until` set on ANY refresh failure. Also add `_is_token_refreshing` with a `_refresh_lock` to prevent concurrent attempts. Set cooldown on exceptions too (network errors count). See `references/song-token-refresh-cooldown.md`.
- **⛔ Python `global` declared after read = un-importable module** — If a function sets `global _var` but reads `_var` before the declaration, Python throws `SyntaxError` at import time. PyInstaller silently excludes the module during Analysis (no build warnings). At runtime `import spotify_handler` raises `ModuleNotFoundError`. Detection: `python3 -c "import spotify_handler"`. Move ALL `global` declarations to the top of the function. See `references/python-global-before-read.md`.
- **⛔ Every `resp.json()` call must catch `ValueError`** — APIs return non-JSON bodies on 429 HTML pages, 502 errors, and empty responses. A bare `resp.json()` throws `JSONDecodeError: Expecting value: line 1 column 1 (char 0)` — cryptic and unhelpful. Wrap with `try: resp.json()` / `except ValueError: return {"error": f"Status {status_code} with non-JSON: {text[:200]}"}`. See `references/safe-json-parse.md`.
See `references/song-queue-worker.md` for the full fixed pattern.

## TTS via edge-tts (. prefix trigger, full config dashboard)

TikFinity-style TTS using a configurable prefix (default `.`) on chat messages. Audio plays through desktop audio (captured by OBS), no overlay needed. Full dashboard tab with enable/disable, voice selector, speed/pitch sliders, permissions, member level minimum, whitelist, and **TTS history log** showing who used TTS, when, and what they said.

- Chat message still goes to Minecraft (`.text` is a regular message with TTS triggered after `log_and_send()`)
- Config file: `tts_config.json` — command, voice, speed, pitch, max_length, cooldowns, member_min_level, permissions
- History file: `tts_history.json` — last 500 entries with user, nick, text, timestamp, voice
- Flask API: `/api/tts/{config,voices,speak,history,history/clear}`
- **Voice effects:** whisper/yell tags. See `references/tts-effects.md`.
- edge_tts generates mp3 in background thread, pygame mixer plays it
- Permission check includes `member_min_level` — when `permission.members` is on, viewer's `member_level` must meet the threshold
- `_test: true` flag in `/api/tts/speak` payload skips permission check — used by dashboard "Speak" button for previewing
- edge_tts must be added to PyInstaller `hiddenimports`
- **TTS History logging** — After successful TTS playback, log entry to `tts_history.json` with user, nick, text (capped at 500 chars), timestamp, voice. Dashboard shows history in TTS side panel with auto-refresh every 10 seconds.
- **⛔ edge_tts rate MUST have +/- prefix** — `Communicate(rate=...)` validates `startswith("+") or startswith("-")`. Speed slider stores `"0%"` → plain `"0"` causes `ValueError: Invalid rate '0'`. Piped through the silent `print()` trap (console=False). Fix: `rate = ("+" + speed) if not speed.startswith(("+","-")) else speed`. Debug via file log, not print.
- **⛔ PyInstaller console=False swallows thread errors** — Background threads with bare `except: print()` silently fail. Always log thread errors to file with `traceback.format_exc()`.

See `references/tts-system.md` for the full implementation pattern including frontend and history logging.

## Safe Refactoring Workflow (from 2026-05-28 Session)

When refactoring a vibecoded codebase, follow this safe workflow to avoid breaking things during live streams:

### Phase 1: Preparation (Safest)

1. **Backup first** - Create timestamped backup excluding build artifacts:
   ```bash
   tar czf "backups/backup_pre_refactor_$(date +%Y%m%d_%H%M%S).tar.gz" \
     --exclude=__pycache__ --exclude=build --exclude=dist --exclude=venv \
     --exclude=backups --exclude=.hermes --exclude=release .
   ```

2. **Clean old backups** - Remove recursive backups that include `backups/` folder or `release/` (they're 1-2GB each and useless):
   ```bash
   # Check what's inside before deleting
   tar tzf backup_*.tar.gz | head -20
   # Look for ./backups/ or ./release/ in the listing
   ```

3. **Create utility modules** - Extract common patterns:
   - `utils.py` - `load_json(file, default)`, `save_json(file, data)` (replaces 38+ duplicate patterns)
   - `constants.py` - All magic numbers, timeouts, limits, file names

4. **Test after each file** - Compile check before moving on:
   ```bash
   python3 -m py_compile utils.py constants.py app.py minecraftDiamond.py actions.py spotify_handler.py
   ```

### Phase 2: Apply Changes

5. **One file at a time** - Update imports, replace patterns, test compilation
6. **Don't change logic, only structure** - Same inputs → same outputs
7. **Use constants instead of magic numbers** - `MAX_TTS_HISTORY = 500` instead of `500` inline

### Phase 3: Split Big Functions (Higher Risk)

8. **Break giant functions** (>100 lines) into 50-line helpers
9. **Keep orchestrator function** that calls the helpers
10. **Test after each split** - Verify behavior unchanged

### What NOT to Refactor

- ✋ Math evaluation logic (amount*N) - WORKS, don't touch
- ✋ Skript files (.sk)
- ✋ Profile configs (.yml)
- ✋ Spotify OAuth flow (complex, working)
- ✋ TikTok Live connection logic (critical)

### Benefits of This Approach

- **Easier debugging** - smaller functions = easier to find bugs
- **Faster development** - add features without touching 200-line functions
- **Less bugs** - proper error handling catches issues early
- **Better readability** - future you (or AI) can understand code faster

### Pitfalls

- **⛔ Refactoring CAN break things** - Always test after each change
- **⛔ Don't refactor during live stream** - Do it off-stream with time to test
- **⛔ Vibecoded code has hidden dependencies** - Be careful with function splits
- **⛔ Silent errors (except: pass) are risky to leave unfixed** - They hide bugs RIGHT NOW
- **Streak delta over-counting bug** - See `references/streak-delta-overcounting-bug.md`

## Code Safety Patterns (from 2026-05-27 Audit)

### Safe Arithmetic Placeholders (Replace eval())

When using template patterns like `{amount*N}` to multiply values, use simple direct multiplication — NOT `eval()` or complex `ast.literal_eval`:

```python
import re as _re

def math_replacer(match):
    expr = match.group(1)  # e.g., "amount*50" or "amount*1500"
    try:
        # Split on operator: "amount*50" -> ["amount", "*", "50"]
        parts = _re.split(r'([+\-*/])', expr, maxsplit=1)
        if len(parts) == 3 and parts[0].strip() == "amount":
            amount_val = int(ctx.get("amount", 1))
            op = parts[1]
            num = int(parts[2].strip())
            if op == "*": return str(amount_val * num)
            elif op == "+": return str(amount_val + num)
            elif op == "-": return str(amount_val - num)
            elif op == "/": return str(amount_val // num) if num else str(amount_val)
        # Fallback: just return amount
        return str(ctx.get("amount", 1))
    except:
        return str(ctx.get("amount", 1))

# ⛔ CRITICAL: Math evaluation MUST run BEFORE template substitution!
# If template sub runs first, {amount*50} becomes {1*50}, and the regex
# looking for {amount...} won't match — multiplication silently fails.
cmd = _re.sub(r'\{(amount[^}]*)\}', math_replacer, cmd)

# Template substitution AFTER math evaluation
for key, val in ctx.items():
    cmd = cmd.replace(f"{{{key}}}", str(val))
```

**Why simple split+multiply over ast.literal_eval:**
- Easier to understand and debug
- No edge cases with regex character filtering
- Direct arithmetic is more predictable than string replacement + eval

**⛔ CRITICAL Processing order pitfall (2026-05-28, caused live-stream breakage):** Math evaluation MUST happen BEFORE template substitution. If you do template substitution first, `{amount*50}` becomes `{1*50}` after `{amount}` is replaced with `1`. Then the regex `r'\{(amount[^}]*)\}'` looks for `{amount...}` but finds `{1*50}` → no match → multiplication silently fails. The user will see 1 TNT instead of 50. **Always evaluate `{amount*N}` patterns FIRST, then substitute remaining variables.** This broke live on stream — user was furious.

**⛔ After ANY rebuild, ALWAYS tell the user to RESTART the app.** The exe being rebuilt does NOT update a running instance. User tests features live during streams and expects immediate results. Common cause of "it's still broken!" after a fix: the app wasn't restarted.

**⛔ When user is LIVE on stream, use the SIMPLEST possible fix.** Do not overcomplicate with ast.literal_eval, regex sanitization, or complex patterns. For `{amount*50}` → just split on `*` and multiply directly. The user was furious when a simple multiply was replaced with complex code that failed silently. If a 5-line fix works, don't write a 20-line "safer" version. Stream = pressure = viewers complaining = keep it simple.

**⛔ DON'T LOOK AT SKRIPT FILES WHEN DEBUGGING TEMPLATE SUBSTITUTION** — When the user reports `{amount*50}` isn't working, the problem is in the Python app's template processing, NOT in the Skript files. The user explicitly said "NOT THE SKRIPT BUT THE APP" and "DONT LOOK UP TO THE SKRIPT FILE BECAUSE THE PROBLEM IS ON THE APP". Focus debugging on `actions.py`'s `_execute_minecraft()` function — that's where template substitution happens. Only check Skript files if the issue is about command syntax (wrong command name, missing arguments).

### Thread-Safe JSON Queue (Read + Write Use Same Lock)

When sharing a JSON file between threads, BOTH reads and writes must use the SAME lock:

```python
_queue_lock = threading.Lock()

def load_queue():
    with _queue_lock:
        if not os.path.exists(QUEUE_FILE):
            return []
        try:
            with open(QUEUE_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []

def save_queue(queue):
    with _queue_lock:
        with open(QUEUE_FILE, 'w') as f:
            json.dump(queue, f, indent=2)
```

Without the lock on load_queue(), a concurrent writer can leave the file partially-written, causing JSONDecodeError in the reader.

### Safe JSON Read with Retry (Cross-Process Race)

When Flask reads JSON files written by the bot subprocess, a thread lock between processes won't work. Use retry-on-error:

```python
def safe_json_read(path, retries=3):
    for attempt in range(retries):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError, ValueError):
            if attempt < retries - 1:
                time.sleep(0.05)
            else:
                return None
    return None
```

### Non-Blocking Token Refresh Lock (Double-Check)

Prevent concurrent token refresh calls with a cooldown + non-blocking lock:

```python
_token_refresh_lock = threading.Lock()
_token_refresh_until = 0

def get_valid_token():
    if time.time() < _token_refresh_until:
        return token
    if not _token_refresh_lock.acquire(blocking=False):
        return token
    try:
        if time.time() < _token_refresh_until:
            return token
        # actual refresh logic...
    finally:
        _token_refresh_lock.release()
```

### Shared Asyncio Event Loop for Flask Threads

Never use asyncio.run() in a Flask request handler. Use a daemon-threaded loop:

```python
_shared_loop = asyncio.new_event_loop()
_loop_thread = threading.Thread(target=_shared_loop.run_forever, daemon=True)
_loop_thread.start()

def run_async(coro):
    import concurrent.futures
    future = asyncio.run_coroutine_threadsafe(coro, _shared_loop)
    return future.result(timeout=30)
```

### Bot Subprocess Orphan Cleanup

Register an atexit handler near the bot_process global:

```python
import atexit

bot_process = None

@atexit.register
def _cleanup_bot():
    global bot_process
    if bot_process is not None and bot_process.poll() is None:
        try:
            bot_process.terminate()
            bot_process.wait(timeout=5)
        except Exception:
            bot_process.kill()
```

## Hot-Reload Pattern (Config Changes Without Restart)

For Flask + TikTokLive subprocess architectures, use a **file-based signal** mechanism to trigger config hot-reloads without killing the live stream.

### Architecture

The Flask dashboard (`app.py`) runs as the parent process. It spawns the TikTokLive bot as a subprocess (`main.py --run-bot`). They share the filesystem.

### Implementation

**app.py (Flask) — signal sender:**
```python
def signal_reload():
    signal_file = os.path.join(BASE_DIR, ".reload_signal")
    try:
        with open(signal_file, "w") as f: f.write("1")
        print("--- Config reload signaled to bot ---")
    except Exception as e:
        print(f"Failed to signal config reload: {e}")
```

Call after config save / profile switch (check bot is running first):
```python
if bot_process is not None and bot_process.poll() is None:
    signal_reload()
```

**minecraftDiamond.py (bot) — polling receiver:**
```python
RELOAD_SIGNAL_FILE = ".reload_signal"

def reload_config():
    global VIP_LIST, GIFTS_WITH_STREAK_DELTA, GIFT_ACTIONS, EVENTS, LIKES_CONFIG, GLOBAL_COMMANDS
    try:
        with open(CONFIG_FILE, "r") as f:
            config = yaml.safe_load(f)
        VIP_LIST = set(config.get("VIP_List", []))
        GIFTS_WITH_STREAK_DELTA = set(config.get("StreakDeltaGifts", []))
        GIFT_ACTIONS = config.get("Gifts", {})
        EVENTS = config.get("Events", {})
        LIKES_CONFIG = config.get("Likes", {})
        GLOBAL_COMMANDS = config.get("GlobalCommands", {})
        print("[HOT-RELOAD] Config reloaded successfully.")
    except Exception as e:
        print(f"[HOT-RELOAD] Failed: {e}")

async def config_watcher():
    while True:
        if os.path.exists(RELOAD_SIGNAL_FILE):
            reload_config()
            try: os.remove(RELOAD_SIGNAL_FILE)
            except: pass
        await asyncio.sleep(3)
```

### ⚠️ CRITICAL: Schedule Inside TikTokLive's Event Loop

**WRONG ❌** — `asyncio.ensure_future()` before `client.run()`:
```python
def run_bot():
    try:
        asyncio.ensure_future(config_watcher())  # orphaned — wrong loop
        client.run(fetch_gift_info=True)
    except Exception: pass
```
`client.run()` creates its own internal event loop. The future is scheduled on the outer default loop and never runs.

**RIGHT ✅** — Schedule from `on_connect` (loop is live):
```python
@client.on(ConnectEvent)
async def on_connect(event: ConnectEvent):
    asyncio.ensure_future(config_watcher())
    # ... stream state, viewer stats, etc.
```

By the time `ConnectEvent` fires, TikTokLive's asyncio loop is running. The task attaches properly.

### What Can Be Hot-Reloaded

| Setting | Can Reload? | Reason |
|---------|------------|--------|
| Gift actions, Event commands, VIP list | ✅ | Runtime globals |
| Streak delta, Likes, Global commands | ✅ | Runtime globals |
| TikTok username, RCON, MC username | ❌ | Module-level init, needs reconnect |

### .gitignore

```
.reload_signal
```

## Bot Reconnection & Resilience

When `client.run()` exits mid-stream (network blip, TikTok server kick, WebSocket timeout), the bot subprocess dies permanently because `run_bot()` is a single-shot call with no retry. The dashboard shows "Not Running" and the user must manually press "Start Bot" again.

### How TikTokLive Handles Disconnects

Reading the library source (`client.py`, `ws_client.py`) reveals two distinct exit paths from `client.run()`:

**Path 1 — Stream actually ended (TikTok sends STREAM_ENDED control message):**
1. `ControlAction.STREAM_ENDED` → library calls `client.disconnect()` → fires `LiveEndEvent`
2. WebSocket closes with code 1000 (OK, clean)
3. `_ws_client_loop` finishes normally (no exception)
4. `client.run()` returns **without raising** — no exception
5. Bot exits cleanly

**Path 2 — Network blip / connection lost (no signal from TikTok):**
1. WebSocket drops (ping timeout, connection reset, error close code)
2. `websockets` library raises `ConnectionClosedError`
3. `_ws_client_loop` crashes with an exception
4. `client.run()` **raises the exception**
5. Bot catches it, prints error, exits

### The Reconnect Pattern (Exception-Based Differentiation)

The presence or absence of an exception from `client.run()` IS the signal:

```python
def run_bot():
    while True:
        try:
            client.run(fetch_gift_info=True)
            # No exception → stream ended normally → STOP
            print("Stream ended. Bot shutting down.")
            break
        except Exception as e:
            # Exception → network/reliability issue → RETRY
            print(f"Disconnected unexpectedly: {e}")
            print("Reconnecting in 5 seconds...")
            time.sleep(5)
            # Loop back to try again — always a fresh ConnectEvent
```

**Why this works:**
- Stream ended → no exception → `break` → bot shuts down like normal
- Network blip → exception → `except` → sleeps → retries forever
- Dashboard "Stop" button → `bot_process.terminate()` → SIGTERM kills the subprocess before the loop can retry. The `while True` loop never gets to decide on its own.

**Why TikTokLive's built-in retry isn't enough:** The library may retry WebSocket connections internally (a few times), but if all retries fail or the disconnect is a clean server-initiated close, it gives up. There's no `auto_reconnect=True` flag. The wrapper loop handles all cases uniformly.

### Pitfalls with Reconnection

**Clearing logs on reconnect wipes session data.** The `on_connect` handler clears `gift_log.json`, `follow_log.json`, `chat_log.json` every time `ConnectEvent` fires. If the bot reconnects to the same stream after a brief network blip, ALL session data from before the blip is lost:

```python
@client.on(ConnectEvent)
async def on_connect(event: ConnectEvent):
    for log_file in ["gift_log.json", "follow_log.json", "chat_log.json"]:
        with open(log_file, "w") as f:  # WIPES existing data
            json.dump([], f)
```

**Implemented fix — room_id comparison (option 1):**

```python
@client.on(ConnectEvent)
async def on_connect(event: ConnectEvent):
    # Check if this is a reconnect to the same stream
    is_reconnect = False
    try:
        if os.path.exists("stream_state.json"):
            with open("stream_state.json", "r", encoding="utf-8") as f:
                prev_state = json.load(f)
            if prev_state.get("room_id") == client.room_id:
                is_reconnect = True
                print(f"[RECONNECT] Same room — preserving stream data.")
    except Exception:
        pass

    if not is_reconnect:
        # Clear logs for FRESH session only
        for log_file in ["gift_log.json", "follow_log.json",
                          "chat_log.json", "active_streaks.json",
                          "superfan_log.json"]:
            with open(log_file, "w") as f:
                json.dump([] if log_file != "active_streaks.json" else {}, f)
        active_streaks.clear()
        # Zero viewer stats
        with open("viewer_stats.json", "w") as f:
            json.dump({"viewers": 0, "total_viewers": 0, ...}, f)

    # Always write stream state (AFTER the is_reconnect check)
    stream_state = {"room_id": client.room_id, ...}
    with open("stream_state.json", "w") as f:
        json.dump(stream_state, f, indent=2)

    # Rest of on_connect: config_watcher, register_events, dump_gifts...
```

**Why room ID works:** Each TikTok live stream gets a unique room_id. If the streamer restarts their stream, it's a new room_id → fresh session. If it's the same room_id, it's a network reconnect → same session. `stream_state.json` gets written AFTER the check, so on the first connect of a new stream there's either no file or a stale file with a different room_id.

**What survives reconnect:** gift_log, follow_log, chat_log, active_streaks (both JSON and in-memory dict), viewer_stats.

**What resets on reconnect:** `started_at` timestamp in stream_state.json (correct — reflects the reconnection time). Config watcher re-registered (idempotent). Available gifts re-dumped (harmless refresh).

**Reconnect loop vs `on_connect` timing:** On each retry, `client.run()` calls `client.start()` which re-fetches room info and reconnects the WebSocket. `ConnectEvent` fires fresh each time. The `on_connect` handler's config_watcher registration is idempotent (just ensures a watcher is running). Stream state gets a new `started_at` timestamp — this is correct behavior for a true reconnect.

**Max retries for true stream end:** If the stream really ended, TikTok sends `STREAM_ENDED` and `client.run()` returns without exception. But what if the library behavior changes or the control message is missed? Add a modest max retry cap (e.g., 10 attempts) as a safety net. After the cap, log "Max reconnection attempts reached — assuming stream ended" and exit.

- `references/v7-research-findings.md` — Detailed findings from the 7.0.0a1 alpha research session (2026-04-30), including proto file paths, event field tables, and comparison with v6 workarounds in TikTokMCIntegrator.
- `references/v7-alpha-logid-fix.md` — Complete fix recipe for the `WebcastPushFrame.log_id` Pydantic validation crash (ge=0 rejects -1). One-liner monkey-patch included.
- `references/pyinstaller-path-resolution.md` — PyInstaller `__file__` vs `sys.executable` bug: frozen exe resolves `__file__` to `_internal/`, causing files to be written to the wrong directory. Pitfall + fix pattern.
- `references/pyinstaller-defender-lock.md` — Windows Defender locks dist/ folder after builds, blocking subsequent builds. Diagnosis, 4 solutions (exclusion, disable, rename fallback, admin), and why Explorer restart doesn't help.
- `references/pyinstaller-windowed-debug-logging.md` — When `console=False` in PyInstaller spec, `print()` output is discarded. Background threads that catch exceptions and only `print()` them create invisible failures (HTTP 200, no audio, no error). Fix: write thread-level errors to a debug log file with `traceback.format_exc()`.
- `references/song-rate-limit-defense.md` — 8s playback cache + reduced polling + non-JSON response handling for "Expecting value: line 1 column 1 (char 0)" crashes from Spotify rate limits.
- `references/song-overlay-progress-sync.md` — Smooth media progress bar pattern: backend cache TTL (3s), frontend local timer interpolation, conditional re-sync (track/play-pause/drift>5s), and force-sync on visibility change. Solves freeze, fast-forward, and pause/resume sync issues.
- `references/song-token-refresh-cooldown.md` — Global token refresh cooldown pattern. Spotify's accounts API bans are 400x harsher than data API (hours vs seconds). `_token_refresh_until` + `_is_token_refreshing` flag + `_refresh_lock` prevent concurrent refresh hammering. Every failed refresh (not just 429) triggers cooldown.
- `references/euler-stream-premium-endpoints.md` — Euler Stream premium API endpoints (`/webcast/chat` for sending chat, `/webcast/user_earnings` for revenue data). **After 3 rounds of investigation (2026-05-23): chat sending is fundamentally paywalled.** Community-tier sign API returns 401 for all endpoints. The `client=ttlive-node` parameter bypasses the 401 on the deprecated `sign_url` endpoint (returns 200 + redirect to premium proxy), but TikTok's `room/chat/` POST returns 403 regardless. The original Node.js v2 library's `sendMessage()` was removed in the v7 rewrite. No viable free path to chat sending exists — this is a deliberate paywall by Isaac Kogan/Euler Stream. Pricing ($50/mo) and full reverse-engineering assessment included.
- `references/tiktok-ecosystem-architecture.md` — TikTokLive ecosystem deep-dive: Isaac Kogan's sign server monopoly across all 6 language ports, zerody→Isaac transition history, how Isaac migrated chat from free direct-POST to paid proxy, reverse engineering difficulty assessment (9.5/10), and viable workarounds for chat sending without paying.
- `references/python-global-before-read.md` — Python `global` must be declared BEFORE variable read in same function. SyntaxError crashes PyInstaller silently (module excluded from build → ModuleNotFoundError at runtime). Detection: `python3 -c "import spotify_handler"`.
- `references/safe-json-parse.md` — Every `resp.json()` wrapped in try/except with non-JSON fallback. Prevents "Expecting value: line 1 column 1 (char 0)" crashes from 429 HTML pages, 502 errors, empty responses.
- `references/flask-file-picker.md` — Native `<input type="file">` pattern for file selection. User explicitly rejected custom modal browsers. Use this for any file upload/selection feature.
- `references/audio-preview-pattern.md` — Audio preview (play/stop) for sound action rows: Flask serve endpoint with path security + HTML5 Audio API toggle pattern.
- `references/js-silent-reference-error.md` — Diagnosis and fix for JS function name mismatch (e.g. esc() vs escHtml()) causing silent blank UI with no error messages.
- `references/song-queue-worker.md` — Background daemon thread pattern that polls Spotify playback and auto-pushes the next queued song when current track ends.
- `references/bot-reconnect-loop.md` — Auto-reconnect wrapper with exception-based differentiation.
- `references/ranking-events.md` — 4 ranking events in TikTokLive 7.0.0a1. Imported but NO handlers — quick win for gaming-rank/top-gifter data.
- `references/tts-system.md` — Text-to-Speech via edge_tts (free, 400+ voices). Architecture: .prefix detection → Flask endpoint → mp3 gen → pygame playback. Full config dashboard.
