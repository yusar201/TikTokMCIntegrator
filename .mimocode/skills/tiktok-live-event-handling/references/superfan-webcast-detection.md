# SuperFan Webcast Detection (2026-06-09)

## Context
Khito observed that TikTokLive's general SuperFan event is unreliable/broken, while SuperFanBox works. The question was whether SuperFan exists on Webcast directly.

## Finding
SuperFan is **not a normal REST route** in this app's current architecture. It is detected from WebSocket/protobuf messages.

### General SuperFan
TikTokLive maps general SuperFan from `BarrageEvent` / `WebcastBarrageMessage`.

Installed library matcher (`TikTokLive/client/client.py`, `handle_custom_event`):

```py
if isinstance(event, BarrageEvent):
    display_types = [
        getattr(event.content, "display_type", None),
        getattr(event.common_barrage_content, "display_type", None),
    ]
    if any("ttlive_superfan_commentnotif_superfanjoined" in dt for dt in display_types):
        return SuperFanJoinEvent().parse(response.payload)
    if any("ttlive_superfan" in dt for dt in display_types):
        return SuperFanEvent().parse(response.payload)
```

Markers:

```text
ttlive_superfan
ttlive_superfan_commentnotif_superfanjoined
```

### SuperFanBox
TikTokLive maps SuperFanBox from `EnvelopeEvent` / `WebcastEnvelopeMessage`.

Matcher:

```py
if isinstance(event, EnvelopeEvent):
    envelope_dt = common_display_type(event.common).lower()
    business_type = getattr(event.envelope_info, "business_type", None)
    if "ttlive_superfanbox" in envelope_dt or int(business_type) == 19:
        return SuperFanBoxEvent().parse(response.payload)
```

Markers:

```text
ttlive_superfanbox
envelope_info.business_type == 19
```

## Why SuperFanBox works but general SuperFan can fail
SuperFanBox has two robust signals: display type + numeric `business_type=19` on `EnvelopeEvent`.

General SuperFan relies on a string marker in two Barrage fields only:

- `event.content.display_type`
- `event.common_barrage_content.display_type`

If TikTok moved the marker to another field, changed the string, emits a different proto type, or only exposes it in raw/common display text, the custom `SuperFanEvent` wrapper will not fire even though raw Webcast still carries the info.

## Debug plan
When general SuperFan does not fire:

1. Add raw `BarrageEvent` logging for display markers:

```py
@client.on(BarrageEvent)
async def debug_barrage(event):
    fields = {
        "content_display_type": getattr(getattr(event, "content", None), "display_type", None),
        "common_barrage_display_type": getattr(getattr(event, "common_barrage_content", None), "display_type", None),
    }
    if any(v for v in fields.values()):
        append_jsonl("barrage_debug.log", fields)
```

2. Add `UnknownEvent` logging if available to catch new/unsupported proto messages.
3. During a stream, trigger/observe a known SuperFan action.
4. Search logs for:

```text
superfan
fan
subscriber
joined
barrage
ttlive_
```

5. Patch TikTokLive/custom matcher locally only after observing the real marker.

## Practical answer
- **Available on Webcast?** Yes, likely in WebSocket/proto, not a simple REST endpoint.
- **General SuperFan route?** No confirmed REST route.
- **Current broken point:** library custom matcher may be too narrow.
- **Best fix path:** raw event sniffing, then widen matcher.
