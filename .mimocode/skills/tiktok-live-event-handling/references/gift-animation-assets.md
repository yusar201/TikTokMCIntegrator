# Gift Animation Assets — Field Reference & Download Pattern

> Reference for the `tiktok-live-event-handling` skill. Read alongside `gift-proto-fields.md`.

## Why a separate reference

The `event.asset` and `event.asset_bundle` fields contain real download URLs, but the path is deep and the field names are misleading (`resource_url` is actually a `ResourceModel` with a `url_list`, not a string). This file documents the exact path + the format inference rules + what to expect from real events.

## Field Path Tree (verified from TikTokLive 7.0.0a1)

### Per-event asset (most common path)

```
WebcastGiftMessage
├── gift: Gift
│   ├── id: int                          # static gift ID, use as cache key
│   ├── diamond_count: int               # coin cost (100+ = animated)
│   ├── is_effect_befview: bool          # has fullscreen entrance effect
│   ├── is_broadcast_gift: bool
│   ├── is_global_gift: bool
│   ├── primary_effect_id: int
│   ├── duration: int                    # animation length (ms)
│   ├── resource_id: int                 # animation resource ID
│   └── gift_struct_hash: str
│
├── asset: AssetsModel | None            # single asset (most common)
│   ├── name: str
│   ├── id: int
│   ├── resource_type: int               # 1=image, 2=video, ?=other
│   ├── md5: str
│   ├── size: int
│   ├── describe: str
│   ├── resource_uri: str                # alternate path, sometimes empty
│   └── resource_url: ResourceModel | None
│       ├── url_list: list[str]          # ← THE URLS (use url_list[0])
│       └── uri: str                     # alternate, usually empty
│
├── asset_bundle: AssetBundle | None     # multi-asset bundles
│   ├── assets: list[AssetsModel]        # each has same resource_url shape
│   └── prefab_bundle: PrefabBundle | None
│
├── is_asset_bundle_gift: bool           # has asset_bundle above
│
├── text_effect: TextEffect | None       # text overlay layout
│   ├── portrait: Detail | None
│   │   ├── text: Text | None            # the gift name formatted
│   │   ├── text_font_size: int
│   │   ├── background: ImageModel | None
│   │   ├── start: int                   # ms offset
│   │   ├── duration: int                # ms length
│   │   ├── x, y, width, height: int     # layout coords
│   │   ├── shadow_dx, shadow_dy, shadow_radius: int
│   │   ├── shadow_color: str
│   │   ├── stroke_color: str
│   │   └── stroke_width: int
│   └── landscape: Detail | None         # same shape, for landscape
│
├── display_duration_ms: int             # how long to play the animation
├── effect_extra: str                    # raw JSON-ish config, often empty
└── color_id: int                        # variant color of the gift
```

### VideoResource (sub-asset within AssetsModel)

```
AssetsModel
├── video_resource_list: list[VideoResource]
│   ├── video_type_name: str             # "mp4", "webm", "lottie" etc
│   ├── video_url: ResourceModel | None
│   │   ├── url_list: list[str]
│   │   └── uri: str
│   └── video_md5: str
└── loki_content: LokiExtraContent | None
    ├── gift_type: str                   # "big_flower" etc
    ├── gift_duration: int               # ms
    ├── model_names: str                 # 3D model names if any
    ├── bef_view_render_fps: int
    ├── bef_view_render_size: BefViewRenderSize
    └── view_overlay: str
```

## Real-World Format Inference

`resource_type` is sometimes wrong. The URL itself is the source of truth:

| URL hint | Ext | Format | Plays in `<video>`? |
|---|---|---|---|
| `.mp4` or no clear hint | `mp4` | H.264 video | ✅ yes |
| `.webm` | `webm` | VP8/VP9 video, often with alpha | ✅ yes (browser support varies) |
| `lottie` or `.json` | `json` | Lottie/Bodymovin vector animation | ⚠️ needs `lottie-web` JS lib |
| `.png` / `.webp` | `webp` | Static image | ✅ yes (`<img>`) |
| Unknown `resource_type` | skip | Sometimes proprietary TikTok-only format | ❌ no |

**Default to `mp4` if no hint** — most animated gifts use MP4.

## Quick Detection Rule

```python
HAS_ANIMATION = (
    event.gift.diamond_count >= 100       # empirical threshold
    and event.gift.is_effect_befview      # fullscreen entrance
) or (
    event.is_asset_bundle_gift            # has bundle
) or (
    event.gift.is_broadcast_gift          # broadcast
) or (
    event.gift.is_global_gift             # cross-screen
)
```

**Most reliable single signal:** `event.asset is not None and event.asset.resource_url is not None and event.asset.resource_url.url_list` — if you can extract a URL, it's downloadable.

## Download + Cache Pattern

Already documented in SKILL.md. Key code skeleton:

```python
# In on_gift handler, after gift is identified
if GIFT_ASSET_DOWNLOADER and diamond_count >= 100:
    asset = getattr(event, "asset", None)
    if asset and getattr(asset, "resource_url", None):
        urls = asset.resource_url.url_list
        if urls:
            url = urls[0]
            ext = "mp4"
            if ".webm" in url.lower(): ext = "webm"
            elif "lottie" in url.lower() or ".json" in url.lower(): ext = "json"
            from gift_assets.downloader import download_gift_asset
            local_path = download_gift_asset(gift_id, url, ext=ext)
            if local_path:
                ctx["asset_url"] = local_path  # e.g. "/gift_assets/gift_1234.mp4"
```

## Why URL caching matters

- TikTok's CDN URLs can be **TTL'd** — 404 after a few minutes for some endpoints
- Repeated gifts of the same type would re-download otherwise
- The manifest.json is the single source of truth — `gift_id → local_url` lookup is O(1)

## Observed Real URLs (from the proto)

- `https://p16-webcast.tiktokcdn.com/img/...` — image assets (webp/png)
- `https://p16-sign-sg.tiktokcdn.com/...` — signed assets (often video)
- `https://p16-live-sg.tiktokcdn.com/...` — live region-specific

**The `tt_target_idc` cookie / region affects which CDN domain you get.** This is why some URLs work in browser but not from a server in another region — TikTok region-locks assets.

## Known Limitations

1. **Some gift animations are TikTok-proprietary** — won't play in browser. Detect by trying to load the file in `<video>` and falling back to a static image overlay if `error` event fires.
2. **`asset_bundle` for some gifts contains 5+ assets** (e.g. multi-stage animations). For v1, only download the first one.
3. **CDN bandwidth costs** — large gifts can be 5-10MB videos. Capping total cache size (e.g. 500MB LRU) is a future improvement.
4. **No copyright clarity** — these assets are TikTok's. Caching them locally is fine for personal use, but don't redistribute.

## Test Pattern (no live stream needed)

To smoke-test the downloader without a real 100+ coin gift event:

```python
# tests/test_gift_assets.py
import os
from gift_assets.downloader import download_gift_asset

# Use a known-good TikTok asset URL (replace with real one you logged from a stream)
TEST_URL = "https://p16-webcast.tiktokcdn.com/img/maliva/webcast-va/..."
result = download_gift_asset(999999, TEST_URL, ext="mp4")
assert result is not None, "Download should succeed"
assert os.path.exists("gift_assets/gift_999999.mp4")
print(f"✅ Cached to {result}")
```

But the **truly authoritative test** is capturing a real event from stream — that's the only way to know the format your specific gifts use. Log `event.to_dict()` for the first 3-5 animated gifts that come through, then check the asset paths.
