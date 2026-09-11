# SuperFan Box Sent vs Claimed Separation

## Context

SuperFan Box can fire twice in live streams:

1. when someone sends / creates the SuperFan Box
2. when someone opens / claims the SuperFan Box

TikTok's visible UI may render both rows almost identically (`Someone opened / triggered SuperFan Box`, `SUPERFAN`, `80X`), so do not assume the UI text reflects the real proto phase.

## Proto path

Current TikTokLive exposes SuperFan Box as `EnvelopeEvent` / custom `SuperFanBoxEvent`.

Useful fields live under `event.envelope_info`:

- `envelope_id` — stable box id; use for dedupe/correlation
- `business_type` — SuperFan Box has been observed as `19`
- `send_user_name` — sender display name, better than `event.user` for boxes
- `send_user_id` — sender id string
- `send_user_avatar` — ImageModel for sender avatar
- `diamond_count` — box value / coin count
- `people_count` — number of claim slots
- `unpack_at` — open/claim time marker
- `create_at` — creation time marker
- `room_id`
- `super_fan_count`

`event.user` can be missing on this build, so `_event_nick(event)` often returns `Someone`. Prefer `envelope_info.send_user_name` for sender-side logs/actions.

## Detection / classification pattern

Extract details first, then classify:

```python
def _superfan_box_details(event) -> dict:
    info = getattr(event, "envelope_info", None)
    details = {"box_source_event": type(event).__name__}
    if info:
        details.update({
            "envelope_id": getattr(info, "envelope_id", ""),
            "sender_name": getattr(info, "send_user_name", ""),
            "sender_id": getattr(info, "send_user_id", ""),
            "diamond_count": getattr(info, "diamond_count", 0),
            "people_count": getattr(info, "people_count", 0),
            "unpack_at": getattr(info, "unpack_at", 0),
            "created_at": getattr(info, "create_at", ""),
        })
    markers = [str(s).lower() for s in _collect_event_strings(event)[:80]]
    details["box_phase"] = _classify_superfan_box_phase(common_dt, markers)
    return details
```

Suggested phase names:

- `superfan_box_sent` — sender-side event; allowed to execute configured `SuperFanBoxEvent` actions
- `superfan_box_claimed` — claim/open-side event; log/feed only by default
- `superfan_box_unknown` — cannot classify yet; log/feed only while collecting markers

Classification heuristic:

```python
def _classify_superfan_box_phase(common_dt: str, markers: list[str]) -> str:
    text = " ".join([common_dt.lower()] + markers)
    if any(token in text for token in ("_sent", " sent", "send", "sender", "commentsection_sent")):
        return "sent"
    if any(token in text for token in ("claim", "claimed", "open", "opened", "unpack", "receive", "received")):
        return "claimed"
    return "unknown"
```

## Action safety rule

Only execute configured `SuperFanBoxEvent` actions for `box_phase == "sent"`.

Claim/open events must be log/feed-only unless the user explicitly creates a separate action path for them. This prevents one physical box from firing rewards twice.

## Dedupe rule

Dedupe by `(envelope_id, event_type)` instead of `(nick, superfan_box)` when possible:

- sender event and claim event can share the same visible name / `Someone`
- raw `EnvelopeEvent` and custom `SuperFanBoxEvent` wrappers may both fire for the same proto
- `envelope_id` is the best correlation key

## Dashboard/logging fields to surface

When logging to `superfan_log.json`, keep compact extra fields so next live test has evidence without dumping the full proto:

- `event_type`: `superfan_box_sent` / `superfan_box_claimed` / `superfan_box_unknown`
- `box_phase`
- `envelope_id`
- `sender_name`
- `sender_id`
- `diamond_count`
- `people_count`
- `common_display_type`
- `business_type`
- `marker_sample` (filtered strings containing `superfan`, `box`, `envelope`, `claim`, `open`)

Dashboard meta should distinguish `BOX SENT`, `BOX CLAIM`, and `BOX?` instead of the ambiguous old text `opened / triggered SuperFan Box`.
