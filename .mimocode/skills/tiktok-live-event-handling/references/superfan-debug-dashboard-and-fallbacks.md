# SuperFan Dashboard + Raw-Event Fallbacks (2026-06-09)

## Session lesson

User needed `Recent SuperFans` on the dashboard for debugging. First implementation only added UI + `SuperFanEvent`/`SuperFanJoinEvent` wrapper handling. User then tested on another stream: visible SuperFan join in TikTok UI, but nothing appeared in dashboard. Conclusion: the installed TikTokLive custom wrappers and the first raw `BarrageEvent` matcher were insufficient for at least some rooms/clients.

## Dashboard pattern

Existing backend already exposed:

```text
GET  /api/stats/superfan
POST /api/stats/superfan/clear
superfan_log.json
```

Frontend additions:

- Add `Recent SuperFans` card beside gifts/follows.
- Poll `/api/stats/superfan` every ~2500ms.
- Render event types:
  - `new_superfan` → bright/gold, noticeable, triggers MC reward
  - `superfan_box` → purple, noticeable
  - `superfan_join` → small/dim/subdued; no reward
  - `superfan_join_ignored` → small/dim/subdued; no reward
  - `subscribe` → blue/neutral if grouped there
- Bump `style.css?v=` and `script.js?v=` cache-busters in `templates/index.html`.

Reason: SuperFan join can happen a lot; make it visible enough for debugging but visually low-priority.

## Detection hierarchy

Use wrappers as fallback, not primary source.

1. **Primary: raw `BarrageEvent`**
   - scan `content.display_type`
   - scan `common_barrage_content.display_type`
   - scan `common.display_text.key` / `display_type` / `default_pattern`

2. **Join fallback: `JoinEvent` user badge scan**
   - some streams expose an existing SuperFan entering as a normal join event with a badge, not a `BarrageEvent` marker.
   - recursively scan `event.user.badges`/nested badge text/icon fields for `superfan`, `super_fan`, `super fan`, `ttlive_superfan`.
   - log as `superfan_join`; never reward.

3. **Probe: `UnknownEvent`**
   - recursively scan unknown payload for superfan-like marker.
   - log to `superfan_debug.log` and optionally dashboard as subdued join.

4. **Fallback wrappers**
   - `SuperFanEvent` → reward only after guard excludes `ttlive_superfan_commentnotif_superfanjoined`.
   - `SuperFanJoinEvent` → log only.
   - `SuperFanBoxEvent` → log box; reward only if product design says so.

## Correct semantics

```python
if "ttlive_superfan_commentnotif_superfanjoined" in marker:
    append_superfan_log(nick, "superfan_join")
    # NO execute_actions
elif "ttlive_superfan" in marker:
    append_superfan_log(nick, "new_superfan")
    await execute_actions(EVENTS.get("SuperFan", []), ctx, send_minecraft_command)
```

Important: check the join marker first because it contains `ttlive_superfan` as a substring.

## Dedupe required

Raw event + custom wrapper may both fire. Use `(nick, event_type)` short-window dedupe (~8s) to prevent double dashboard logs / double MC rewards.

## Debug file

Write lightweight discovery lines to:

```text
superfan_debug.log
```

Use it when user says TikTok UI showed SuperFan but dashboard did not. Log marker sources (`raw_barrage`, `join_badge`, `unknown_probe`, `custom_event`) so the next iteration can tighten matching.

## Deploy reminder

After this class of change, use `./deploy.sh` only, then verify `release/TikTokMCIntegrator.exe` mtime and remove accidental nested `release/TikTokMCIntegrator/` if a wrong build path was used earlier in the session. See `tiktokmc-build-deploy`.
