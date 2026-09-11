# TikTok Live Algorithm & Viewer Retention

Key patterns for growing a TikTok Live audience (from research + user experience, 2026-05-26).

## The "Spike Then Drop" Pattern
- TikTok tests your live with ~50-200 viewers in the first 2-5 minutes
- If retention is good → push to 500-1000
- If people bounce → STOP pushing, back to existing viewers only
- **User sees:** viewer count jumps at start, then drops to ~10 (existing loyal viewers)

## First 5 Seconds is Everything
- New viewers land on your live. They see Minecraft. They don't know about the gift-interaction hook unless it's **screamingly obvious in the first frame**
- If the other streamer has an overlay or title that makes the interactivity obvious immediately, people stay to see it happen
- **The "what is this?" bounce:** On mobile, people scroll past lives in < 2 seconds. If your thumbnail/title doesn't communicate "YOU control this game with gifts" clearly, they swipe

## Why "Same Content" ≠ Same Results
The algorithm scores on **weighted signals**, not a checklist:
- **Account authority/trust score** — account age, posting history, past live performance
- **First 60 seconds retention** — returning viewers are weighted WAY higher than new ones
- **Snowball threshold** — around 50-100 viewers where the algorithm treats you differently
- **Engagement rate** — comments, shares, gifts per viewer

## What Actually Moves the Needle
1. **Get returning viewers** — encourage follows + regular schedule
2. **Retention > reach** — keep people watching longer
3. **Watch time > everything** — the #1 metric for live push is average watch time
4. **Comment engagement** — reply to comments out loud
5. **Stream consistency** — same days, same time, same duration for 2+ weeks

## For TikTokMCIntegrator Specifically
- The bot interaction is a **huge retention advantage** — not many streamers have that hook
- Make the gift interaction **visible in the first 5 seconds** — big overlay text saying "GIFTS CONTROL MINECRAFT" or similar
- New viewers don't know what they're watching — the interaction must be obvious immediately
- Audio quality matters — bad mic, game audio too loud = instant bounce on mobile

## Shadowban Avoidance (from ProxyEngineering research)
TikTok doesn't primarily flag on IP. It flags on a **fingerprint cluster score**:
- WebGL renderer string consistency
- Canvas noise variance patterns
- Gyroscope/accelerometer absence on mobile sessions
- Touch event timing distributions
- Battery API polling behavior
- Timezone vs DNS resolver location gaps

**Key insight:** Residential proxies are a distraction. The device fingerprint matters more than the IP.
