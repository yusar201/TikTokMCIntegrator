# Standalone Gallery/Event Listener for Any TikTok Live Room

A minimal script that connects to **any** TikTok live room (not just the bot's own username) to debug rare events like `GiftPanelUpdateEvent`, `GoalUpdateEvent`, or gallery-related `BarrageEvent` fields. Useful when you need to observe real gallery/progress traffic without needing the bot's own stream to be active.

## The pattern

```python
import asyncio, yaml
from pathlib import Path
from TikTokLive import TikTokLiveClient
from TikTokLive.client.web.web_settings import WebDefaults
from TikTokLive.events import (
    GiftPanelUpdateEvent, GoalUpdateEvent, BarrageEvent,
    ConnectEvent,
)

TARGET = "some_live_user"           # any currently-live TikTok user
CONFIG_FILE = Path("config/config.yml")

cfg = yaml.safe_load(open(CONFIG_FILE)) or {}
EULER_KEY = cfg.get("Settings", {}).get("EulerApiKey", "")

WebDefaults.tiktok_sign_api_key = EULER_KEY
WebDefaults.tiktok_sign_url = "https://tiktok-legacy.eulerstream.com"

client = TikTokLiveClient(unique_id=f"@{TARGET}")

@client.on(ConnectEvent)
async def on_connect(e):
    print(f"Connected to @{TARGET} (room_id={client.room_id})")

@client.on(GiftPanelUpdateEvent)
async def on_panel(e):
    gd = e.gallery_data
    if gd and gd.progress:
        for gid, td in gd.progress.items():
            print(f"[PANEL] gift={gid} goal={td.goal_count} sponsor={td.current_sponsor_id}")

@client.on(GoalUpdateEvent)
async def on_goal(e):
    print(f"[GOAL] contributor={e.contributor_id} count={e.contribute_count} score={e.contribute_score}")
    if e.goal and hasattr(e.goal, 'sub_goals'):
        for sg in (e.goal.sub_goals or []):
            print(f"  sub_goal id={sg.id} progress={sg.progress}/{sg.target}")

async def main():
    await client.connect()
    await asyncio.sleep(600)  # listen for 10 min
    client.disconnect()

asyncio.run(main())
```

## Key details

- **Does not need to be the streamer.** `TikTokLiveClient(unique_id="@any_user")` connects as a viewer to that user's room. Any viewer can observe all public events (gifts, chat, follows, gallery, goals, barrages).
- **Requires Euler API key** from the project's own config (connects to EulerStream to sign the WebSocket URL). The key is still needed for signing; only the target user changes.
- **EulerStream host** currently set to `https://tiktok-legacy.eulerstream.com` (the legacy host that's working as of June 2026).
- **Platform:** WEB (default). Some events like `GiftPanelUpdateEvent` may not fire on WEB — only confirmed `GoalUpdateEvent` works on WEB as of 2026-06-25.
- **10 min window** is usually enough to see at least one iteration of periodic gallery progress events during an active stream.

## What was tested (2026-06-25, @zuuttz)

- **`GoalUpdateEvent` → CONFIRMED on WEB** — fired at ~3.5 minutes: `sub_goal id=7934 progress=48/100`, `contributor_id=7322191303352255531`, `score=1`, `gift_repeat=1`.
- **`GiftPanelUpdateEvent` → NOT observed** — did not fire in a 5-minute window. Likely requires someone to **complete** a gallery goal (hit the target), not just make incremental progress.
- **`BarrageEvent.gallery_gift_id` → NOT observed** — no gallery-tagged barrages in the test window.

## Cleanup

Delete test script + log file when done:
```bash
rm -f gallery_listener.py gallery_listener.log
```
