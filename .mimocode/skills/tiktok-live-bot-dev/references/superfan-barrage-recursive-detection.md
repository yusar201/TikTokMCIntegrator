# SuperFan detection via raw BarrageEvent recursive scan

Session: 2026-06-09, TikTokMCIntegrator.

## Problem
TikTokLive custom SuperFan wrappers were unreliable for this setup. Existing SuperFan joins and new SuperFan events did not consistently surface through fixed fields like `content.display_type` / `common_barrage_content.display_type` or through `SuperFanEvent` / `SuperFanJoinEvent`.

## Verified source
Raw websocket debug showed the real event as:

```text
WebcastBarrageMessage
payload_hex_prefix ... 74746c6976655f7375
```

`74746c6976655f7375` decodes to `ttlive_su...`, confirming SuperFan markers lived inside the barrage payload.

## Working pattern
Use `@client.on(BarrageEvent)` as the primary detector, then recursively collect strings from the parsed event object instead of reading only fixed fields.

Key markers observed live:

```text
ttlive_superfan_commentnotif_superfanjoined
ttlive_superfan_commentnotif_someonebecamesuperfan
becoming_super_fan_entrace_bg.png
becoming_super_fan_lv1
becomingsuperfanlv1
```

Console proof for new SuperFan:

```text
[BARRAGE DEBUG] display_types=[] superfan_strings=['ttlive_superfan_commentnotif_someonebecamesuperfan', ...]
======NEW SUPERFAN DETECTED======
SuperFan: TeamWiffle source=raw_barrage_recursive
```

## Implementation guidance
- Keep custom `SuperFanEvent`, `SuperFanJoinEvent`, `SuperFanBoxEvent` handlers as fallbacks only.
- Add de-dupe between raw barrage + wrappers so rewards/logs do not double-trigger.
- Treat `ttlive_superfan_commentnotif_superfanjoined` as existing SuperFan join; usually log-only/no reward because it is noisy.
- Treat `ttlive_superfan_commentnotif_someonebecamesuperfan` / `becoming_super_fan*` as new SuperFan; trigger the configured event actions.
- If debugging field drift, attach `WebsocketResponseEvent` probe and log method names + payload hex prefixes around the suspected event.
- Dashboard `Recent SuperFans` can show all event types; OBS SuperFan overlay should filter to `event_type === 'new_superfan'` when the user wants alerts only for newly converted SuperFans.

## Pitfalls
- Do not claim SuperFan is fixed just because dashboard display was added; verify detector path fires and event actions execute.
- Do not rely on `display_types` being populated; verified working case had `display_types=[]`.
- Do not route SuperFan join to the same reward/action path unless user explicitly wants noisy join actions.
