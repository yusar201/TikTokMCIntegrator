# TikTokMCIntegrator

**A production-oriented TikTok Live control plane for Minecraft.** TikTok gifts, chat, follows, subscriptions, shares, and engagement events become configurable Minecraft actions, stream overlays, and moderated Spotify song requests.

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)

> Built for live operation: configuration changes are hot-reloaded, failures are visible in the dashboard, and packaged Windows deployments preserve runtime state.

---

## Features

- **TikTok Live event bridge** — connects through `TikTokLive` and maps live events to actions with contextual variables such as `{user}`, `{mc}`, `{gift_name}`, and `{amount}`.
- **Minecraft command dispatch** — supports standard RCON, a local Forge helper mod for single-player/modded play, and ServerTap REST.
- **Native operator dashboard** — Flask API served in a Windows `pywebview` shell with system-tray control, live bot console, connection checks, profiles, and configuration UI.
- **OBS-ready overlays** — compact browser-source overlays for gifts, top supporters, goals, streaks, TTS, and Spotify. Idle overlays stay hidden and dashboard previews are resource-gated.
- **Local-first Spotify queue** — durable SQLite-backed request queue with a `queued → playing → played` lifecycle, permissions, instant revoke, and controlled playback transitions.
- **Pluggable add-on system** — drop-in packs that add their own commands, overlays, settings panes, and persistent state. No add-ons are bundled with this repository (see [Add-ons](#add-ons)).
- **Gift Card Studio** — designs and exports gift cards to PNG or animated GIF.
- **Safe deploy workflow** — the PyInstaller build/deploy script keeps user configuration, tokens, assets, add-ons, logs, and stream state out of the replaceable application artifacts.

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
    └── add-on loader ──► optional drop-in packs (commands, overlays, state)
```

## Requirements

- **Windows** for the packaged desktop app and native shell (the core runs anywhere Python does).
- **Python 3.11+**
- A Minecraft server or world reachable through one of the [connectors](#connectors).
- Optional: a Spotify developer app if you want song requests.

## Quick start

### 1. Clone and install

```bash
git clone https://github.com/yusar201/TikTokMCIntegrator.git
cd TikTokMCIntegrator

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

## Add-ons

Add-ons are self-contained packs discovered at startup by `addon_loader.py` and exposed through `routes/addons.py`. A pack can contribute Minecraft commands, action mappings, OBS overlays, a settings pane, and its own persistent state directory.

**No add-ons ship with this repository.** The add-on directories under `addons/` are excluded from version control because the packs are personal, separately distributed projects. A fresh clone therefore starts with the framework available and zero packs installed:

- the loader scans `addons/` and finds nothing — this is expected;
- the dashboard shows an empty add-on list;
- every core feature works normally.

To use a pack, place it at `addons/<pack_id>/` with an `addon.yml` manifest (or `addon.json`); it is picked up on the next start.

## Testing

```bash
python -m pytest -q
```

The suite covers event→action mapping, add-on loader discovery and runtime registry, reconnect backoff, overlay idle/animation budgets, coin-goal cache behavior, Spotify queue transitions, gift deltas, Gift Card Studio rendering, and dashboard behaviour.

## Windows build and deploy

From WSL, use the deploy script:

```bash
./deploy.sh --full    # backend/bundle changes
./deploy.sh --fast    # static/template-only changes
```

The release layout is always:

```text
release/
├── TikTokMCIntegrator.exe
├── _internal/
├── templates/
└── static/
```

The deploy flow preserves runtime configuration, stream data, logs, assets, and user-installed add-ons. **Restart the application after deployment** so the new executable and assets are loaded.

## Repository layout

```text
app.py                     Flask app, dashboard routes, wiring
main.py                    entry point and desktop shell
minecraft_main.py          TikTok event → Minecraft action pipeline
actions.py                 action mapping and command templating
event_registry.py          live event registration
addon_loader.py            add-on discovery
addon_runtime_registry.py  add-on runtime instances and config
gift_card_studio/          card designer and PNG/GIF export
routes/                    HTTP blueprints
static/ templates/         dashboard UI and OBS overlays
tests/                     pytest suite plus JS/parity helpers
tools/                     maintenance and inspection scripts
docs/ plans/               design notes and handoff records
deploy.sh                  build and deploy
config.example.yml         public configuration template
```

## Contributing

Issues and pull requests are welcome. Before opening a PR:

1. Run the test suite (`python -m pytest -q`).
2. Keep new configuration values runtime-readable — settings that affect a live stream must take effect without restarting the bot.
3. Do not commit credentials, tokens, stream data, or build artifacts (see below).

## Repository hygiene

No TikTok credentials, RCON passwords, Spotify tokens, active profiles, stream logs, user data, build artifacts, or local recovery snapshots belong in this repository. Use `config.example.yml` as the public configuration template. These paths are Git-ignored and must stay that way:

```text
config/     data/     logs/     release/     addons/
```

## License

MIT — see [LICENSE](LICENSE).
