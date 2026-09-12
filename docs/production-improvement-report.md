# TikTokMCIntegrator Production Improvement Report

**Status:** completed for the verified source/release snapshot on 2026-08-19.

## Scope and protected invariants

- Minecraft command dispatch remains immediate: event handlers start the existing connector thread and do not introduce a shared queue, batching, serialization, or artificial wait.
- Runtime state under `config/`, `data/`, `logs/`, `assets/`, and `addons/` is preserved by deployment.
- Stream-facing settings continue to be read live where the existing implementation requires it.

## Implemented changes

### Dashboard PC-lightness guard

`static/script.js` now schedules dashboard polling through a small guarded scheduler. Polls are skipped when the document is hidden, and a second request for the same endpoint is not started while the previous request is still running. Existing polling cadences and endpoint behavior remain unchanged.

### Source path correctness

`paths.py` now resolves the development project root from the module location instead of walking one directory above it. This fixes source-mode add-on/catalog resolution on Windows and Linux. Frozen builds continue to resolve from the executable directory.

### Release configuration correction

The release default profile's Friendship Necklace/Frozen Hands mapping now uses `rush frozenhands {mc} {amount*10} add {user}`. The obsolete `disableminegift` mapping is absent, and the matching remove action remains present.

### Gift persistence offload

`minecraft_main.py` now awaits `points_store.record_gift` through `asyncio.to_thread`. The write remains ordered before the handler continues, but SQLite I/O no longer occupies the TikTok event-loop thread. Minecraft dispatch remains unchanged.

### Offline replay benchmark

`tools/event_replay_benchmark.py` replays local gift bookkeeping into temporary SQLite/JSON state without contacting TikTok, Minecraft, Spotify, or OBS. It reports elapsed time, P50/P95/max timings, and temporary artifact sizes.

- Full Windows test suite: **501 passed**.
- Focused Linux tests: **38 passed**.
- JavaScript syntax check: `node --check static/script.js` passed.
- Python compilation: `python -m compileall` passed for application modules.
- Ranking microbenchmark: median **0.011 ms** per update, P95 **0.017 ms**.
- SQLite gift-write microbenchmark: median **13.855 ms**, P95 **17.243 ms**, worst **38.712 ms** for a temporary local database.
- Bounded JSON-write microbenchmark: median **1.614 ms**, P95 **2.205 ms** for a 500-entry synthetic payload.
- Temporary benchmark processes were stopped after measurement.

## Audit findings not changed deliberately

### Minecraft connector dispatch

The current design creates a daemon thread per command and opens the selected connector for that command. Static analysis identifies possible burst-time thread/handshake pressure, but no live stream measurement proved a user-visible latency or reliability defect. Changing this path could add command delay or alter ordering, so it was left unchanged.

### Points SQLite writes

Gift writes are synchronous from the gift handler and measurable at roughly 14–17 ms locally. Moving them to a worker could improve event-loop responsiveness but would change failure/order semantics. No change was made without a production-like burst test and an explicit contract for write completion.

### Spotify chat handling

Chat song search/playback operations include synchronous external API work. This is a plausible event-loop hotspot, but moving it asynchronously requires preserving permission checks, command ordering, feedback, and local queue authority. No speculative rewrite was shipped.

### Overlay polling

Overlay cadence is intentionally different by overlay type; song progress uses a 250 ms display update while data polling remains slower. Existing overlay tests enforce idle and animation budgets. No broad cadence reduction was made because it could visibly degrade stream presentation.

## Deployment verification

The canonical `./deploy.sh --full` completed successfully. Verified afterward:

- `release/TikTokMCIntegrator.exe` exists.
- `release/_internal/`, `release/templates/`, and `release/static/` exist.
- Frontend copies exist in both release locations.
- `release/config/`, `data/`, `logs/`, `assets/`, and `addons/` exist.
- No stale nested `release/TikTokMCIntegrator/` directory exists.
- Release executable mtime is fresh relative to the built executable.

## Remaining live-validation boundary

A real TikTok/Minecraft stream endurance run was not performed in this pass. CPU/RAM/thread behavior under an actual gift burst, Minecraft connector outage, and several-hour OBS session therefore remains a live validation item rather than a claimed result. The shipped change is intentionally limited to the dashboard polling guard and path/config corrections that passed the available automated gates.
