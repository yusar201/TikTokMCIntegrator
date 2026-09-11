# TikTokLive SuperFan vs SuperFanJoin vs SuperFanBox

Session: 2026-06-09, TikTokMCIntegrator `minecraftDiamond.py`.

## Durable finding

TikTokLive's custom SuperFan events are WebSocket/proto-derived, not normal REST routes.

Installed TikTokLive matcher logic:

```py
# BarrageEvent markers
if "ttlive_superfan_commentnotif_superfanjoined" in display_type:
    return SuperFanJoinEvent()
if "ttlive_superfan" in display_type:
    return SuperFanEvent()

# EnvelopeEvent marker / business type
if "ttlive_superfanbox" in common_display_type or int(envelope_info.business_type) == 19:
    return SuperFanBoxEvent()
```

## Implementation rule

For Minecraft rewards:

- `SuperFanEvent` = viewer becomes a new superfan → reward allowed.
- `SuperFanJoinEvent` = existing superfan joins room → log only; **do not reward**.
- `SuperFanBoxEvent` = superfan gift box/envelope → separate event, reward if configured.

Because broad substring matching can misclassify `ttlive_superfan_commentnotif_superfanjoined` as generic `ttlive_superfan`, always either:

1. Register a separate `@client.on(SuperFanJoinEvent)` handler that logs only, and
2. Add a defensive guard inside `on_superfan`:

```py
def _superfan_display_types(event) -> list[str]:
    display_types = []
    for obj in (getattr(event, "content", None), getattr(event, "common_barrage_content", None)):
        dt = getattr(obj, "display_type", None) if obj else None
        if isinstance(dt, str) and dt:
            display_types.append(dt.lower())
    return display_types

@client.on(SuperFanEvent)
async def on_superfan(event):
    display_types = _superfan_display_types(event)
    if any("ttlive_superfan_commentnotif_superfanjoined" in dt for dt in display_types):
        append_superfan_log(nick, "superfan_join_ignored")
        return
    # real new-superfan reward here
```

## Verification

- Run `python -m py_compile minecraftDiamond.py` before build.
- Keep temporary `BarrageEvent` / `EnvelopeEvent` debug logging while validating rare live events.
- SuperFanBox working does **not** prove general SuperFan works; box uses `EnvelopeEvent` + business type 19, while general SuperFan uses `BarrageEvent` display markers.
