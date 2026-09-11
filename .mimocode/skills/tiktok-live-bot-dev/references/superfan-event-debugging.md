# SuperFan event debugging notes

Context: TikTok SuperFan join/new-superfan events may not arrive through TikTokLive's high-level `SuperFanEvent` / `SuperFanJoinEvent` wrappers. Treat wrappers as convenience only, not source of truth.

## Durable workflow

1. **Dashboard ≠ detector.** If Recent SuperFans stays empty, first verify whether `superfan_log.json` changes. If the JSON/log is empty, the detector is blind; do not keep tweaking UI.
2. **Use raw event probes before claiming a fix.** Add/log `WebsocketResponseEvent` batches to identify actual message methods emitted during a visible TikTok SuperFan join.
3. **Make debug log deterministic.** Create `superfan_debug.log` on bot start under `BASE_DIR` so absence of the file means old build/not running, not merely no matches.
4. **For frozen exe paths:** write debug/runtime logs with `BASE_DIR = dirname(sys.executable) if sys.frozen else dirname(__file__)`. Expected release path: `D:\Ikhito\Code\TikTokMCIntegrator\release\superfan_debug.log`.
5. **Broad probe ladder:**
   - `BarrageEvent`: `content.display_type`, `common_barrage_content.display_type`, `common.display_text.key`
   - `SuperFanEvent` / `SuperFanJoinEvent`: fallback only, with dedupe
   - `JoinEvent`: scan user badges for `superfan`, `super_fan`, `super fan`, `ttlive_superfan`
   - `UnknownEvent`: probe superfan-like markers
   - `WebsocketResponseEvent`: log raw `message.method` + payload length/prefix for `Barrage/Envelope/Member/Social/Notice/Toast/Fan/Sub` methods
6. **Dedupe rewards.** Raw event + wrapper can both fire. Dedupe by `(nick, event_type)` over a short window before executing Minecraft reward.
7. **Join is noisy.** Existing SuperFan join should log as subdued UI only; no Minecraft reward. New SuperFan should be prominent + trigger reward.

## Pitfalls

- Do not assume `ttlive_superfan_commentnotif_superfanjoined` still appears in `BarrageEvent`; some rooms may display a SuperFan join in TikTok UI while TikTokLive exposes it elsewhere or not through current wrappers.
- Do not report success based on code shape alone. User must test on live stream; if no dashboard/log entry appears, collect `superfan_debug.log` and map the raw method.
- Do not write `superfan_debug.log` relative to current working directory; packaged exe cwd can differ. Use `BASE_DIR`.
