# SuperFan live markers + routing decisions (verified 2026-06-09)

Session-specific evidence from TikTokMCIntegrator live testing. Use this when SuperFan-related events misroute, trigger the wrong Minecraft action, or fail to appear in Recent SuperFans.

## Confirmed event sources

### New SuperFan
Observed console:

```text
[BARRAGE DEBUG] display_types=[] superfan_strings=['ttlive_superfan_commentnotif_someonebecamesuperfan', ...]
======NEW SUPERFAN DETECTED======
SuperFan: TeamWiffle source=raw_barrage_recursive
```

Reliable route:

```text
WebcastBarrageMessage -> BarrageEvent -> recursive string scan -> new_superfan
```

Confirmed new-superfan markers:

```text
ttlive_superfan_commentnotif_someonebecamesuperfan
becoming_super_fan*
becomingsuperfan*
```

Only these should call `_trigger_new_superfan()` and run Minecraft reward/action commands.

### Existing SuperFan joined
Confirmed route:

```text
WebcastBarrageMessage -> BarrageEvent -> recursive string scan -> superfan_join
```

Marker:

```text
ttlive_superfan_commentnotif_superfanjoined
```

Decision: log to Recent SuperFans only; no Minecraft reward/action unless the user explicitly asks to wire a separate `SuperFanJoinEvent` action.

### SuperFan level upgrade
Observed console:

```text
======NEW SUPERFAN DETECTED======
SuperFan: Kamryne Ellis source=raw_barrage_recursive
display_types=['super_fan_upgrade']
```

This was a false positive. Correct routing:

```text
super_fan_upgrade | superfan_upgrade -> event_type=superfan_upgrade -> log-only
```

Never route upgrade to `new_superfan`; it must not show the new-superfan OBS overlay or run Minecraft reward/action commands.

### SuperFan Gift Box
Observed console:

```text
[ENVELOPE DEBUG] common_display_type=ttlive_superFanBox_commentSection_sent | business_type=UNKNOWN(19)
AttributeError: 'SuperFanBoxEvent' object has no attribute 'user'
```

Correct route:

```text
EnvelopeEvent -> common_display_type contains superfanbox OR business_type contains 19 -> superfan_box_*
```

`SuperFanBoxEvent` currently subclasses `EnvelopeEvent` in this TikTokLive build and may have no `.user`. This was confirmed from installed TikTokLive source:

```text
SuperFanBoxEvent -> EnvelopeEvent -> BaseEvent -> WebcastEnvelopeMessage
```

The source docstring says `SuperFanBoxEvent` is a subset of `EnvelopeEvent`, matched by `ttlive_superfanbox` display type or `business_type == 19`. This means normal treasure/coin boxes also use `EnvelopeEvent`; never treat every envelope as SuperFan. Filter strictly by the SuperFanBox display marker or business type 19.

SuperFanBox send/open split (2026-06-22): TikTok may emit a first event when the box is sent and a second when someone opens/claims it. Log phase-specific event types so the dashboard can show what happened and actions do not double-trigger:

```text
superfan_box_sent     -> sender-side event; may execute explicitly configured SuperFanBoxEvent actions
superfan_box_claimed  -> open/claim event; log/feed/debug only
superfan_box_unknown  -> SuperFanBox subtype but phase marker not yet identified; log/feed/debug only
```

Extract and preserve richer fields from `event.envelope_info` where present:

```text
send_user_name -> sender_name / display name
send_user_id   -> sender_id / stable-ish sender field from envelope
diamond_count, people_count, envelope_id, envelope_idc, unpack_at, create_at, room_id, super_fan_count
```

Action routing pattern (never fall back to `SuperFan` actions):

```python
if box_phase == "sent":
    await execute_actions(EVENTS.get("SuperFanBoxEvent", []), ctx, send_minecraft_command)
else:
    # claim/unknown is log-only to prevent duplicate triggers
    return
```

Legacy rows in preserved `superfan_log.json` may still show `event_type="superfan_box"`, `nick="Someone"`, and no phase fields. Treat those as old data, not evidence that new phase splitting failed.

## Recommended classifier order

Do not use a broad generic `"superfan" in marker` decision for rewards. Classify specific markers first:

```python
markers = display_types + superfan_strings
join_hit = any("ttlive_superfan_commentnotif_superfanjoined" in s for s in markers)
upgrade_hit = any("super_fan_upgrade" in s or "superfan_upgrade" in s for s in markers)
new_hit = any(
    "ttlive_superfan_commentnotif_someonebecamesuperfan" in s
    or "becoming_super_fan" in s
    or "becomingsuperfan" in s
    for s in markers
)
```

Routing:

```text
join_hit    -> superfan_join    -> log-only/no reward
upgrade_hit -> superfan_upgrade -> log-only/no reward
new_hit     -> new_superfan     -> log + overlay + reward/action
```

## Recent SuperFans payload shape

For richer dashboard rows, write:

```json
{
  "nick": "display name",
  "unique_id": "handle",
  "avatar_url": "https://...",
  "tags": "vip,superfan,member",
  "badges": [],
  "event_type": "new_superfan|superfan_join|superfan_upgrade|superfan_box",
  "timestamp": 123456.0
}
```

OBS SuperFan overlay should continue filtering to only:

```js
event_type === 'new_superfan'
```

## Runtime log hygiene

Deploy preserves runtime state such as `release/superfan_log.json`. If a bad row appears every startup, inspect the preserved JSON before assuming a fresh live event. Example fixed 2026-06-09:

```json
{"nick":"Someone","unique_id":"","event_type":"superfan_join"}
```

Guard pattern:

```python
if event_type in ("superfan_join", "superfan_join_ignored") and nick == "Someone" and not unique_id:
    return
```

This keeps unknown join noise out of Recent SuperFans while still allowing real new SuperFan / box events to log.

## EulerStream incident note

On 2026-06-09 EulerStream reported `/webcast/anchors/{unique_id}/room_id` and `/webcast/bulk_live_check` issues on the primary host. Temporary workaround:

```python
WebDefaults.tiktok_sign_url = "https://tiktok-legacy.eulerstream.com"
```

This is temporary; remove/revert once the upstream incident is resolved.
