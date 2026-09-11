# SuperFan detection via raw BarrageEvent / WebcastBarrageMessage (2026-06)

## Verified problem
TikTokLive wrapper/custom SuperFan events were unreliable for Khito's TikTokMCIntegrator. `SuperFanEvent` / `SuperFanJoinEvent` did not consistently fire, and fixed `BarrageEvent` fields like `content.display_type` / `common_barrage_content.display_type` were often empty.

## Verified working path
Raw TikTok websocket emitted:

```text
WebcastBarrageMessage
```

TikTokLive parsed it as `BarrageEvent`, but the SuperFan markers were buried deeper in parsed proto object strings. The working detector recursively scans the whole `BarrageEvent` object for strings.

## New SuperFan marker observed live
Console sample:

```text
[BARRAGE DEBUG] display_types=[] superfan_strings=['ttlive_superfan_commentnotif_someonebecamesuperfan', ...]
======NEW SUPERFAN DETECTED======
SuperFan: TeamWiffle source=raw_barrage_recursive
```

Markers/strings observed:

```text
ttlive_superfan_commentnotif_someonebecamesuperfan
becoming_super_fan_entrace_bg.png
becoming_super_fan_lv1
becomingsuperfanlv1
```

## Existing SuperFan join
Existing SuperFan join also arrives via `WebcastBarrageMessage`, not reliably via wrapper events. Detect join marker separately and log only; do not trigger reward.

Known join marker pattern:

```text
ttlive_superfan_commentnotif_superfanjoined
```

## Implementation pattern
1. Keep `@client.on(BarrageEvent)` as primary detector.
2. Extract all strings recursively from the parsed event object (`vars(obj)`, lists, dicts, common proto fields).
3. Filter strings containing `superfan`, `super_fan`, or `ttlive_superfan`.
4. If marker contains `ttlive_superfan_commentnotif_superfanjoined` → append `superfan_join`, no reward.
5. If marker contains `ttlive_superfan_commentnotif_someonebecamesuperfan` or generic `ttlive_superfan` new-superfan strings → append `new_superfan` and run reward.
6. Keep wrapper handlers only as fallback; dedupe by `(nick, event_type)` to avoid double reward.

## Overlay behavior
Dashboard Recent SuperFans may show all event types (`new_superfan`, `superfan_join`, `superfan_box`, `subscribe`). OBS SuperFan overlay should filter to `event_type === 'new_superfan'` only, because existing SuperFan joins happen often and are noise.

Patch pattern in `templates/overlay.html`:

```js
const newEntries = entries.slice(lastSfCount)
  .filter(e => (e.event_type || e.type || '') === 'new_superfan');
```

## Debugging pattern
If SuperFan stops working again, add a temporary `WebsocketResponseEvent` probe that logs batch methods and payload hex prefixes. In this session the smoking gun was:

```text
WS_METHOD method=WebcastBarrageMessage payload_len=14337 payload_hex_prefix=...74746c6976655f7375
```

`74746c6976655f7375` decodes to `ttlive_su...`, confirming the payload carried a SuperFan marker even when parsed fixed fields were empty.

## Pitfalls
- Do not rely only on `SuperFanEvent` / `SuperFanJoinEvent`; wrappers may not fire.
- Do not rely only on `display_type`; verified `display_types=[]` while marker existed deeper.
- Do not show `superfan_join` on OBS full-screen overlay; it happens a lot.
- Keep dashboard log and OBS overlay semantics separate: dashboard = debugging/all events, overlay = new SuperFan only.
