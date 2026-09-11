# Gift Gallery Proto Fields — `GiftPanelUpdateEvent` & Related Types

Discovered 2026-06-25 in TikTokLive 7.0.0a1. "Gift Gallery" is TikTok's stream-side feature where the gift panel tracks gift-sending progress toward periodic goals. Three proto surfaces carry gallery data; none are handled in the bot yet.

## 1. `GiftPanelUpdateEvent` (primary — most useful)

Fires when TikTok's gift panel/gallery UI updates during a live stream. Registered in `event_registry.py` but has **zero handler** in `minecraft_main.py`.

```python
class GiftPanelUpdateEvent(BaseEvent, WebcastGiftPanelUpdateMessage):
    common: Optional[CommonMessageData]
    room_id: int
    timestamp: int
    gallery_data: Optional[GalleryData]    # ← gift progress tracking
    goal_data: Optional[GoalData]
    room_based_gift_data: Optional[RoomBasedGiftData]
    strategy_context: str
```

### `GalleryData`

```python
class GalleryData(betterproto2.Message):
    progress: dict[int, TitleData]   # keyed by gift/period ID
    period: int                       # time period identifier
    end_time_in_ms: int              # when the gallery period ends
```

### `TitleData`

```python
class TitleData(betterproto2.Message):
    goal_count: int           # target coin count for this gift
    current_sponsor_id: int   # user ID of current top sponsor
```

**Practical use:** Track progress toward gift goals in the gallery. The `progress` dict maps gift IDs to their goal + current leader. `period` + `end_time_in_ms` tell you when the gallery window resets. Could drive a "gift goal" overlay or dashboard metric.

### `GoalData` (also on GiftPanelUpdateEvent)

```python
class GoalData(betterproto2.Message):
    status: int                          # goal state
    goal_progress: dict[int, Progress]   # keyed by goal ID
```

### `RoomBasedGiftData`

```python
class RoomBasedGiftData(betterproto2.Message):
    room_based_gifts: dict[int, RoomBasedGifts]  # keyed by gift ID
```

## 2. `BarrageEvent` gallery fields (secondary — on marquee messages)

`BarrageEvent` (scrolling marquee messages) carries gallery fields but they're currently unused — the bot's `on_barrage_superfan` handler only does recursive string scanning for SuperFan markers and ignores gallery data.

```python
class BarrageEvent(BaseEvent, WebcastBarrageMessage):
    # ... 50+ fields ...
    gallery_gift_id: int                                    # ID of the gallery gift
    gift_gallery_params: Optional[BarrageTypeGiftGalleryParam]  # sender/receiver
```

### `BarrageTypeGiftGalleryParam`

```python
class BarrageTypeGiftGalleryParam(betterproto2.Message):
    from_user_id: int   # who sent the gallery gift
    to_user_id: int     # who received it (usually the streamer)
```

## 3. `LinkMicBattleEvent` league/gallery badges (PK battles)

During PK/linkmic battles, the gallery badge info appears as a league info map:

```python
class LinkMicBattleEvent(BaseEvent, WebcastLinkMicBattleMessage):
    # ... many battle fields ...
    league_info_map: Dict[int, GiftGalleryBadgeInfo]  # keyed by league ID
```

### `GiftGalleryBadgeInfo`

```python
class GiftGalleryBadgeInfo(betterproto2.Message):
    league_info: Optional[GiftGalleryBadgeSection]
    gallery_info: Optional[GiftGalleryBadgeSection]
    background_color: str
    separator_color: str
    dark_mode_background_color: str
    league_name: str
    schema: str
```

### `GiftGalleryBadgeSection`

```python
class GiftGalleryBadgeSection(betterproto2.Message):
    icon: Optional[ImageModel]           # badge icon URL
    display_text: Optional[LinkMicGiftGalleryDisplayText]  # text to show
    should_show: bool                     # whether to display
    dark_mode_icon: Optional[ImageModel]  # dark-mode variant
```

## Current bot status (as of 2026-06-25)

| Event | In `event_registry.py`? | Handler in `minecraft_main.py`? | Gallery fields used? |
|-------|--------------------------|----------------------------------|----------------------|
| `GiftPanelUpdateEvent` | ✅ (category: gifts, priority: low, no template vars) | ❌ no `@client.on()` | ❌ |
| `BarrageEvent` | ✅ | ✅ `on_barrage_superfan` (SuperFan only) | ❌ (gallery fields ignored) |
| `LinkMicBattleEvent` | ✅ | ❌ no import/handler | ❌ |

## To wire up `GiftPanelUpdateEvent`

```python
from TikTokLive.events import GiftPanelUpdateEvent

@client.on(GiftPanelUpdateEvent)
async def on_gift_panel_update(event: GiftPanelUpdateEvent):
    gallery = event.gallery_data
    if not gallery or not gallery.progress:
        return
    for gift_id, title_data in gallery.progress.items():
        goal = title_data.goal_count
        sponsor = title_data.current_sponsor_id
        # Write to a JSON state file for overlay/dashboard to poll
        # gallery.period and gallery.end_time_in_ms for window tracking
```

Add a `_evt()` entry in `event_registry.py` with template vars like `gift_id`, `goal_count`, `current_sponsor_id`, `period`, `end_time_in_ms` if you want users to configure actions for it.