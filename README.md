# TikTokMCIntegrator

**A production-oriented TikTok Live control plane for Minecraft.** TikTok gifts, chat, follows, subscriptions, shares, and engagement events become configurable Minecraft actions, stream overlays, and moderated Spotify song requests.

> Built for live operation: configuration changes are hot-reloaded, failures are visible in the dashboard, and packaged Windows deployments preserve runtime state.

## What it does

- **TikTok Live event bridge** — connects through `TikTokLive` and maps live events to actions with contextual variables such as `{user}`, `{mc}`, `{gift_name}`, and `{amount}`.
- **Minecraft command dispatch** — supports standard RCON, a local Forge helper for single-player/modded play, and ServerTap REST.
- **Native operator dashboard** — Flask API served in a Windows `pywebview` shell with system-tray control, live bot console, connection checks, profiles, and configuration UI.
- **OBS-ready overlays** — compact browser overlays for gifts, top supporters, goals, streaks, TTS, Spotify, and OneBlock. Idle overlays stay hidden and dashboard previews are resource-gated.
- **Local-first Spotify queue** — durable SQLite-backed request queue with `queued → playing → played` lifecycle, permissions, instant revoke, and controlled playback transitions.
- **Optional OneBlock add-on** — phase-aware Objective Rush game mode with a local Minecraft helper API, action packs, overlay, deterministic simulations, and an isolated headless runtime.
- **Safe deploy workflow** — PyInstaller build/deploy script keeps user configuration, tokens, assets, add-ons, logs, and stream state out of the replaceable application artifacts.

## Architecture

```text
TikTok Live
    │
    ▼
TikTokLive client ──► minecraft_main.py ──► RCON / Forge helper / ServerTap ──► Minecraft
    │                         │
    │                         ├── Spotify request worker
    │                         └── live config reload + reconnect policy
    ▼
Flask API + dashboard (app.py) ──► OBS overlays / native Windows shell
    │
    └── Optional add-on loader ──► OneBlock Objective Rush helper + overlays
```

## Stack

- **Python 3.11+** · Flask · Waitress · TikTokLive · PyYAML
- **Minecraft integration** · RCON · Forge local helper · ServerTap REST
- **Desktop and streaming UI** · pywebview / WebView2 · pystray · HTML/CSS/JS · OBS browser sources
- **Music and media** · Spotify Web API · edge-tts · pygame
- **Packaging and tests** · PyInstaller · pytest

## Quick start (development)

### 1. Create a virtual environment and install dependencies

```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# Linux/macOS
# source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Create local runtime configuration

Runtime configuration and stream data are intentionally ignored by Git.

```bash
mkdir config
copy config.example.yml config\config.yml   # Windows CMD
# cp config.example.yml config/config.yml    # Linux/macOS/WSL
```

Edit `config/config.yml` and set at least:

```yaml
Settings:
  TikTokUsername: "@your_tiktok_account"
  MinecraftUsername: "YourMinecraftName"

Rcon:
  Host: "127.0.0.1"
  Port: 25575
  Password: "YOUR_RCON_PASSWORD"
```

### 3. Run

```bash
python main.py
```

The native dashboard opens on `http://127.0.0.1:5000`. Start the bot from the dashboard after verifying the connector.

## Connectors

| Connector | Best for | Configuration |
|---|---|---|
| **RCON** | Dedicated Minecraft servers | `Rcon` block in `config/config.yml` |
| **Forge helper** | Local/single-player modded Minecraft | `Forge` block, default `127.0.0.1:5942` |
| **ServerTap** | ServerTap-compatible Paper/Spigot setups | `ServerTap` block, default `127.0.0.1:4567` |

Connector selection is read from config at runtime, so operators can change it without restarting the bot process.

## Spotify queue model

Song requests are deliberately **not** sent to Spotify's remote queue. The app maintains a local queue with these states:

```text
queued → playing → played
```

A worker advances playback, `!skip` advances locally, and `!revoke` removes the request immediately. This avoids Spotify queue drift and keeps moderation authoritative inside the stream application.

## Optional OneBlock Objective Rush add-on

The bundled add-on lives in `addons/oneblock/`. It provides a phase-aware ten-win challenge layer over OneBlock, with persistent state, anti-repeat objective selection, local helper integration, OBS overlay, and simulation tooling.

- Add-on guide: [`addons/oneblock/README.md`](addons/oneblock/README.md)
- Headless local runtime: `python objective_rush_headless.py`
- Objective simulation: `python addons/oneblock/tools/simulate_objective_rush.py --runs 1000 --phase 6`

## Testing

```bash
python -m pytest tests \
  test_actions_concurrency.py \
  test_gift_delta_tracker.py \
  test_spotify_dashboard_queue_remove.py \
  test_spotify_queue_transition_timing.py \
  test_stats_chat_pagination.py \
  test_tts_warmup.py -q
```

The suite covers Objective Rush selection/state transitions, add-on discovery, reconnect backoff, overlay idle/animation budgets, coin-goal cache behavior, queue transitions, gift deltas, and dashboard behavior.

## Windows build and deploy

From WSL, use the safe deploy script:

```bash
./deploy.sh --full
```

For static/template-only changes:

```bash
./deploy.sh --fast
```

The release layout is always:

```text
release/
├── TikTokMCIntegrator.exe
├── _internal/
├── templates/
└── static/
```

The deploy flow preserves runtime configuration, stream data, logs, assets, and user-installed add-ons. **Restart the application after deployment** so the new executable/assets are loaded.

## Repository hygiene

No TikTok credentials, RCON passwords, Spotify tokens, active profiles, stream logs, user data, build artifacts, or local recovery snapshots belong in this repository. Use `config.example.yml` as the public configuration template.

## License

MIT
