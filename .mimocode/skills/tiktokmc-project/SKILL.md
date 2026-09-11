---
name: tiktokmc-project
description: "TikTokMCIntegrator project primer and workflow router — what the app is, hard project rules (deploy, live-config, tests, single-instance), which skill to load for which subsystem, and the handoff protocol for coordinating changes with other AI agents working on this repo."
---

# TikTokMCIntegrator — Project Primer & Router

Load the specific skill for your task (see "Skill map" below) **before** touching code in that area. This file is the entry point; the specific skills carry the depth.

## What this project is

A local Windows desktop app (`release/TikTokMCIntegrator.exe`) that connects TikTok LIVE events to Minecraft and other stream tools:

- **Python backend** (Flask + SocketIO + Waitress on `127.0.0.1:5000`): TikTok LIVE connection (`TikTokLive 7.0.1`), gift/comment/like/follow events → user-configured actions, Spotify song queue, TTS, SQLite state (`data/points.db`), gift catalog, Gift Roulette, Gift Card Studio.
- **Native desktop shell** (`main.py`): pywebview window + system tray + splash; single-instance enforced (`single_instance.py`).
- **Minecraft side** (separate repo, out of scope for deploy): Forge 1.20.1 helper mods (`tiktokbridge` on 127.0.0.1:5942, `survivalrushbridge` on 5943) receive commands via RCON/socket from the Python app.
- **Add-ons** (`addons/`): `oneblock` (Objective Rush) and `survival_rush` (Survival Rush) — Python owns objective selection/lifecycle; Forge owns world/native-command authority.
- **OBS overlays**: browser sources served from the app (`templates/overlay.html` + per-addon overlay files).

## Hard rules (never break these)

1. **Deploy only via `./deploy.sh`** (`--full` for backend/Python changes, `--fast` for templates/static only). Never hand-copy into `release/`; never `rm -rf release/` (it holds live runtime state: `config/`, `data/`, `logs/`, user addons). Never use `build.bat`.
2. **The exe must be closed before a `--full` deploy** — a running exe locks `_internal/*.pyd` and the deploy silently half-fails. Check the process first, verify exe mtime after.
3. **Live-stream settings take effect without restarting the bot.** Read config at event time; never cache startup constants that the dashboard can change mid-stream.
4. **Never add delay/serialization/batching to Minecraft command dispatch.** Command responsiveness is the top priority; any performance change needs measured before/after evidence of no latency regression.
5. **Spotify requests use the app's local queue** (`queued → playing → played` in `song_queue.json`); never push into Spotify's own queue.
6. **Overlays stay compact, corner-friendly, dark Minecraft-style panels, hidden while idle.** No glass/glow/blur/gradients.
7. **Full test suite runs with `C:\Python313\python.exe -m pytest`** (that interpreter has TikTokLive + Pillow + pytest). A bare `python`/`pip` may hit a different interpreter — always use the full path.
8. **Second exe launch must focus the existing window, never start a second instance** (`single_instance.py` — keep it working).

## Skill map — load before working in an area

| Area | Skill |
|---|---|
| Build, deploy, release verification | `tiktokmc-build-deploy` |
| TikTokLive events, gifts, catalog, SuperFan, upstream intake | `tiktok-live-event-handling` |
| Broad app dev: events, overlays, TTS, reconnects, packaging, OneBlock | `tiktok-live-bot-dev` |
| OBS overlay system (overlay.html, preview mode, restyling) | `tiktokmc-overlay-system` |
| Spotify song queue architecture | `spotify-song-queue-architecture` |
| Gift Card Studio | `gift-card-studio-development` |
| Desktop shell (pywebview, splash, tray, single-instance) | `tiktokmc-desktop-shell` |
| Log-only mode / connection testing | `tiktokmc-log-only-mode` |

## Handoff protocol (multi-agent coordination)

This repo is worked on by multiple AI agents (Hermes + MiMo Code). Coordination rules:

1. **Work on a branch** (`mimo/<task>` or similar), commit with clear messages. Never edit the same files as another agent's in-flight work — serialize on `docs/HANDOFF.md`.
2. **Before starting a session:** read `docs/HANDOFF.md` (latest entries first) and `git log --oneline -10` to see what the other agent changed.
3. **After finishing a change — even a small one — append an entry at the TOP of `docs/HANDOFF.md`:**
   ```markdown
   ## YYYY-MM-DD HH:MM — <one-line what> (by <agent>)
   - Branch/commit: <branch, short hash>
   - Files: <touched files>
   - Tests: <what was run + result, or "not run">
   - Deployed: yes/no (+ how verified)
   - Pending: <what remains / what the other agent should know>
   ```
4. **Never rewrite or delete older handoff entries.** The log is append-only history.
5. **If your change collides with a file another agent recently touched** (see their handoff entry), note the overlap in your entry and prefer asking the user before overwriting.
6. The companion agent (Hermes) reads this log to review/diff/verify your changes. Write it as if a careful reviewer will diff every claim — only claim tests/deploy you actually ran.
