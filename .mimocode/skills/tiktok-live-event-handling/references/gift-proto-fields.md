# Gift Event Proto Fields — Field-Level Reference

Full field dump from TikTokLive 7.0.0a1 protobuf for animation/effect handling.

## `WebcastGiftMessage` (the event you receive)

| Field | Type | Purpose |
|---|---|---|
| `gift` | Gift \| None | The gift definition (name, coins, effects) |
| `gift_id` | int | Same as gift.id |
| `user` | User \| None | Sender |
| `to_user` | User \| None | Recipient |
| `repeat_count` | int | Current streak count |
| `combo_count` | int | Total combo count |
| `repeat_end` | int | 1 = last in streak (used to detect streak end) |
| `group_count` | int | Group gift count |
| `text_effect` | TextEffect \| None | Text overlay layout (portrait + landscape) |
| `asset` | AssetsModel \| None | **Animation asset with download URL** |
| `is_asset_bundle_gift` | bool | Whether this gift has an asset bundle |
| `asset_bundle` | AssetBundle \| None | **List of animation assets** |
| `display_duration_ms` | int | How long to show the animation (ms) |
| `interactive_gift_info` | InteractiveGiftInfo \| None | Cross-screen animation config |
| `color_id` | int | Color variant of the gift |
| `effect_extra` | str | Raw extra effect data (JSON string) |
| `is_first_sent` | bool | First in a series |
| `fan_ticket_count` | int | Fan tickets this gift earned |

## `Gift` (the gift definition, via `event.gift`)

| Field | Type | Purpose |
|---|---|---|
| `id` | int | Gift numeric ID |
| `name` | str | Gift display name (e.g. "Rose", "Galaxy") |
| `diamond_count` | int | Coin cost — **100+ = animated on TikTok** |
| `type` | int | Gift type enum (0=normal, 3=streakable) |
| `gift_sub_type` | int | More granular type |
| `duration` | int | Animation duration (ms) |
| `primary_effect_id` | int | Effect/animation ID |
| `is_broadcast_gift` | bool | Broadcast across room |
| `is_effect_befview` | bool | **Has fullscreen entrance effect** |
| `is_global_gift` | bool | **Cross-screen/animated gift** |
| `is_random_gift` | bool | Random gift with unknown outcome |
| `is_box_gift` | bool | Gift box (lootbox) |
| `gold_effect` | str | Gold/high-value effect string |
| `resource_id` | int | Resource/animation ID |
| `gift_resources` | dict[str, GiftResource] | Map of resource URLs by key |
| `color_infos` | list[GiftColorInfo] | Color/effect variants |
| `is_gallery_gift` | bool | Gallery-type gift |
| `gift_sub_type` | int | Sub-type for special handling |
| `lock_info` | GiftLockInfo \| None | Gift lock/completion info |

## `TextEffect` (text overlay layout, via `event.text_effect`)

```
TextEffect
├── portrait  → Detail (vertical layout)
│   ├── text              → formatted text
│   ├── background        → background image URL
│   ├── start, duration   → animation timing
│   ├── x, y, width, height → screen position
│   └── shadow/stroke     → text effects
└── landscape → Detail (horizontal layout, same structure)
```

## `AssetsModel` (animation asset, via `event.asset`)

| Field | Type | Purpose |
|---|---|---|
| `id` | int | Asset ID |
| `name` | str | Asset name |
| `resource_uri` | str | TikTok internal URI |
| `resource_url` | ResourceModel \| None | **Downloadable URL for the animation** |
| `resource_type` | int | 0=unknown, 1=image, 2=video, etc. |
| `md5` | str | MD5 of the asset |
| `size` | int | Size in bytes |
| `video_resource_list` | list[VideoResource] | Video variants (multiple formats) |

## `AssetBundle` (multiple assets, via `event.asset_bundle`)

```
AssetBundle
├── assets          → list[AssetsModel]  (one of each resource)
└── prefab_bundle   → PrefabBundle | None (prefab configuration)
```

## Animation Detection — Thresholds

```python
# Best indicator for "has full TikTok-style gift animation"
BROADCAST_FULLSCREEN = (
    event.gift.is_effect_befview is True and
    event.gift.is_broadcast_gift is True
)

# Second-best: asset bundle present
HAS_ASSET_BUNDLE = event.is_asset_bundle_gift is True

# Diamond threshold (empirical — check current TikTok values)
# 1 diamond ≈ 1 coin (not real money, token value)
# 100+ = animated overlay, 1000+ = fullscreen extravaganza
DIAMOND_BASED = event.gift.diamond_count >= 100

# Global gifts have cross-screen animations
GLOBAL_GIFT = event.gift.is_global_gift is True
```

## Practical Usage

```python
@client.on(GiftEvent)
async def on_gift(event: GiftEvent):
    gift_name = event.gift.name
    coins = event.gift.diamond_count
    sender = event.user.nickname
    
    # Check if this gift has animation
    has_animation = (
        event.gift.is_effect_befview or
        event.is_asset_bundle_gift or
        coins >= 100
    )
    
    if has_animation:
        # You can download the animation URL:
        if event.asset and event.asset.resource_url:
            anim_url = event.asset.resource_url.url_list[0]  # type: ignore[index]
            # Render in overlay as video or Lottie
        
        # You can get the text overlay layout:
        if event.text_effect and event.text_effect.portrait:
            layout = event.text_effect.portrait
            # Text position: layout.x, layout.y
            # Background image: layout.background.url if layout.background
            # Duration: layout.duration
    
    # display_duration_ms tells you how long to show the overlay
    show_for_ms = event.display_duration_ms or event.gift.duration
```
