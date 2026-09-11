# SuperFan via WebcastBarrageMessage recursive scan (verified 2026-06)

## Verified failure
`SuperFanEvent` / `SuperFanJoinEvent` wrappers and narrow `BarrageEvent` field checks were unreliable. A visible SuperFan join produced no dashboard update until raw websocket probing was added.

## Debug evidence
Temporary `WebsocketResponseEvent` probe showed:

```text
WS_METHOD method=WebcastBarrageMessage payload_len=14337 payload_hex_prefix=...74746c6976655f7375
```

The hex prefix decodes to `ttlive_su...`, proving the SuperFan marker was inside a `WebcastBarrageMessage` even when parsed fixed fields were empty.

## Working detector
Primary handler:

```python
@client.on(BarrageEvent)
async def on_barrage_superfan(event: BarrageEvent):
    strings = _collect_event_strings(event)
    superfan_strings = [s for s in strings if "superfan" in s or "super_fan" in s or "ttlive_superfan" in s]
```

`_collect_event_strings` should recursively scan:
- strings / bytes
- dict/list/tuple/set values
- `vars(obj).values()` for betterproto/proto objects
- known fields: `display_text`, `key`, `display_type`, `content`, `common_barrage_content`, `public_area_message_common`, `event`, badge/image/text fields

## Live new-superfan marker
Observed console:

```text
[BARRAGE DEBUG] display_types=[] superfan_strings=['ttlive_superfan_commentnotif_someonebecamesuperfan', ...]
======NEW SUPERFAN DETECTED======
SuperFan: TeamWiffle source=raw_barrage_recursive
```

Markers/strings:

```text
ttlive_superfan_commentnotif_someonebecamesuperfan
becoming_super_fan_entrace_bg.png
becoming_super_fan_lv1
becomingsuperfanlv1
```

## Join vs new-superfan
Check specific join marker before generic `ttlive_superfan`:

```text
ttlive_superfan_commentnotif_superfanjoined
```

Join → log only (`event_type: superfan_join`), no reward.

New SuperFan → `event_type: new_superfan`, dashboard log, reward/action.

## OBS overlay rule
Dashboard Recent SuperFans may show all event types for debugging. The OBS SuperFan overlay should only show `new_superfan`:

```js
const newEntries = entries.slice(lastSfCount)
  .filter(e => (e.event_type || e.type || '') === 'new_superfan');
```

Reason: existing SuperFan joins happen often and should stay subtle/dashboard-only.

## Pitfalls
- Do not rely on `display_type`; verified `display_types=[]` during a real new SuperFan.
- Do not rely on wrappers as primary detector.
- Do not reward `superfan_join` or `superfan_join_ignored`.
- Keep a short-lived `WebsocketResponseEvent` probe available for future TikTok payload changes, but remove/disable noisy logging after mapping the marker.
