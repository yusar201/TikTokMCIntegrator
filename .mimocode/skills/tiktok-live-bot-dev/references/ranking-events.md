# TikTokLive Ranking & Leaderboard Events

The TikTokLive library exposes 4 ranking/leaderboard events. All 4 are imported
in `event_registry.py` of TikTokMCIntegrator but **none have a handler registered
in `minecraftDiamond.py`** — the events fire and get discarded. Adding handlers
for any of these is a one-day task that surfaces useful stream data.

## Event Summary (from installed TikTokLive 7.0.0a1)

| Event | Purpose | Key Fields | Useful For |
|---|---|---|---|
| `GameRankNotifyEvent` | Gaming ranking notification ("Top 100 in [Game]") | `msg_type`, `notify_text` | Game-specific rank badges |
| `RankUpdateEvent` | Streamer rank changes (periodic update) | `rank_priority`, `tabs`, `tab_info`, `updates` | Top-N display in overlay |
| `RankTextEvent` | Rank display text (badge earned/lost) | `content`, `rank_type`, `self_get_badge_msg`, `other_get_badge_msg`, `user_enigma_info` | TTS: "You're now in the top 50!" |
| `HourlyRankRewardEvent` | Hourly rank reward — list of winners | `winners: list[HourlyRankRewardInfo]` | Hourly recap, top gifters alert |

## Discovery Command

```python
from TikTokLive.events.proto_events import (
    GameRankNotifyEvent, RankUpdateEvent,
    RankTextEvent, HourlyRankRewardEvent
)
import inspect
for cls in [GameRankNotifyEvent, RankUpdateEvent, RankTextEvent, HourlyRankRewardEvent]:
    sig = inspect.signature(cls)
    print(f"=== {cls.__name__} ===")
    for name, p in sig.parameters.items():
        print(f"  {name}: {p.annotation}")
```

Or list all proto events:

```python
from TikTokLive.events import proto_events
print(sorted(proto_events.__all__))
```

## What Needs to Be Done in TikTokMCIntegrator

To surface ranking data in the bot, three things are required for each event:

1. **Handler in `minecraftDiamond.py`** — `@client.add_listener` decorator
2. **Template variables in `actions.py`** — exposes fields to the rule engine (e.g. `{rank_msg}`, `{rank_user}`)
3. **Optional UI surfacing in `templates/index.html`** — overlay widget

### Example: HourlyRankRewardEvent handler stub

```python
@client.add_listener(HourlyRankRewardEvent)
async def on_hourly_rank_reward(event: HourlyRankRewardEvent):
    """Fires when streamer receives an hourly ranking reward."""
    try:
        winners = event.winners or []
        for w in winners:
            # HourlyRankRewardInfo has .user and .score fields
            # Add to overlay, log, or trigger TTS based on config
            logger.info(f"Hourly rank winner: {w}")
    except Exception as e:
        logger.exception(f"Hourly rank reward handler error: {e}")
```

## Relationship to Existing `superfan_log.json` Pattern

`RankUpdateEvent` and `HourlyRankRewardEvent` are similar in spirit to
`SuperFanEvent` — they all give you "top users in some category" data. Follow
the same pattern: append to a JSON log file + emit a custom event that the
rule engine can match against.

## Gotchas

- `RankUpdateEvent` fires VERY frequently (TikTok pings every few seconds with
  current standings). Don't TTS/chat-spam on every fire — debounce or only react
  to **rank changes** (compare new rank_priority to last seen).
- `RankTextEvent.rank_type` is a `ProfitRankType` enum (gift-based ranking).
  Filter by rank_type if you only care about one category.
- `GameRankNotifyEvent` is the gaming-specific one but the gaming context
  (which game) is encoded in the text, not a structured field. Pattern-match
  in `notify_text` if you want to route by game.
