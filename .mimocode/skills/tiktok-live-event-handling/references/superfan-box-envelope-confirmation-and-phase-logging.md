# SuperFan Box = EnvelopeEvent subtype + phase logging (2026-06-22)

## What was confirmed

SuperFan Box is not a separate top-level proto family in the installed TikTokLive build. Source inspection showed:

```text
SuperFanBoxEvent -> EnvelopeEvent -> BaseEvent -> WebcastEnvelopeMessage
```

`SuperFanBoxEvent` source says it is emitted for a **super-fan envelope (gift box)** and is a subset of `EnvelopeEvent`, matched by either:

```text
common.display_text.display_type carrying `ttlive_superfanbox`
OR envelope_info.business_type == BusinessTypeSuperFanBox (= 19)
```

This reconciles the user’s observation: normal treasure/coin boxes are also `EnvelopeEvent`, but SuperFan Box is a filtered envelope subtype. Never treat all `EnvelopeEvent`s as SuperFan.

## Working detection rule

```python
common_dt = common_display_type(event.common) if event.common else ""
biz_type = getattr(event.envelope_info, "business_type", None) if event.envelope_info else None

is_superfan_box = (
    common_dt and "superfanbox" in common_dt.lower().replace("_", "")
) or biz_type == 19 or "19" in str(biz_type)
```

## Sender fields available on `envelope_info`

Source inspection of `MessageRedEnvelopInfo` showed useful fields for dashboard/action context:

- `envelope_id`
- `business_type`
- `envelope_idc`
- `send_user_name`
- `send_user_id`
- `send_user_avatar`
- `diamond_count`
- `people_count`
- `unpack_at`
- `create_at`
- `room_id`
- `follow_show_status`
- `skin_id`
- `vote_count`
- `super_fan_count`

Use these instead of `event.user`; `SuperFanBoxEvent` may not have `.user`.

## Phase separation pattern

Because the user observed two UI events — one when someone sends the SuperFan Box and one when someone opens/claims it — classify into separate local event types:

```text
superfan_box_sent     -> sender-side event; may run configured SuperFanBoxEvent actions
superfan_box_claimed  -> open/claim event; log/feed-only
superfan_box_unknown  -> confirmed SuperFanBox, but marker not enough yet; log/feed-only until live evidence improves classifier
```

Initial classifier heuristic:

```python
text = " ".join([common_dt.lower()] + markers)
if any(t in text for t in ("_sent", " sent", "send", "sender", "commentsection_sent")):
    phase = "sent"
elif any(t in text for t in ("claim", "claimed", "open", "opened", "unpack", "receive", "received")):
    phase = "claimed"
else:
    phase = "unknown"
```

Log compact marker samples (`marker_sample`) and envelope metadata so a rare future live capture can refine the split without requiring another code deploy.

## Dashboard behavior for old rows

Legacy rows with:

```json
{"event_type": "superfan_box", "nick": "Someone"}
```

should render as a neutral “SuperFan Box event — collecting phase data” state. They do not prove whether the new send/claim classifier works; they lack the new fields.

## Pitfall

Do not confuse “`EnvelopeEvent` is used for normal treasure boxes” with “SuperFan Box is not an envelope.” Both are true: TikTok reuses the envelope proto for multiple box mechanics. Always require the SuperFan-specific marker/business type before routing to SuperFan logic.