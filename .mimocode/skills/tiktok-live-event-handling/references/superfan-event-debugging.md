# TikTokLive SuperFan Event Debugging

Use when implementing/reviewing SuperFan, SuperFanJoin, or SuperFanBox behavior.

## Event separation

| Event | Meaning | Reward? |
|---|---|---|
| `SuperFanEvent` | Viewer became a new SuperFan | Yes |
| `SuperFanJoinEvent` | Existing SuperFan joined the room | No — log/debug only |
| `SuperFanBoxEvent` | SuperFan box/envelope event | Project-specific, usually log + configured action |

## Marker guard

`SuperFanJoinEvent` marker contains generic `ttlive_superfan`, so broad substring matching causes false positives.

```python
dt = display_type.lower()
if "ttlive_superfan_commentnotif_superfanjoined" in dt:
    # existing superfan joined; log only
    return
elif "ttlive_superfan" in dt:
    # new superfan; trigger reward
    ...
```

Keep a hard guard inside the `SuperFanEvent` handler too, because a join notice can be misrouted by library/custom matcher changes.

## Dashboard/debug pattern

File IPC: `superfan_log.json`.

Types:
- `new_superfan` — prominent/gold
- `superfan_box` — prominent/purple
- `superfan_join` — subdued/small/low-opacity (noisy)
- `superfan_join_ignored` — subdued guard/debug entry
- `subscribe` — optional blue/sub style

Routes:
```text
GET  /api/stats/superfan
POST /api/stats/superfan/clear
```

Frontend: poll ~2.5s, render `Recent SuperFans`, make join entries visually quiet so reward-triggering events stand out.

## Test constraints

New SuperFan is rare/expensive. Safer tests:
1. `python -m py_compile ...`
2. `node --check static/script.js` when available
3. append synthetic `superfan_log.json` entries in dev/release
4. live watch: joins log but never trigger Minecraft reward
