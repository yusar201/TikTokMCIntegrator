# TikTokMCIntegrator 🎮⚡

**TikTok Live → Minecraft RCON bridge.** Connect your TikTok Live stream to your Minecraft server — gifts, comments, likes, and follows trigger real in-game actions in real time.

---

## Features

- **85+ TikTok Live Events** — Gift, Comment, Like, Follow, SuperFan, Barrage, and more
- **Real-time Minecraft Integration** — Events instantly execute RCON commands on your server
- **Web Dashboard** — Flask-powered UI to control the bot, view logs, and configure everything
- **Smart Gift System** — Map any TikTok gift to custom Minecraft commands with {user} and {amount} variables
- **Profile Management** — Create multiple YAML profiles for different games/streamers
- **Spotify Integration** — !song requests from chat → Spotify queue
- **TTS with Effects** — Text-to-speech (normal, whisper, yell) for chat messages
- **Streak & Badge System** — Track viewer interactions, gifter levels, member status
- **Chat Filter** — Tier-based filtering (gifter level, member level)
- **VIP System** — Whitelist trusted viewers for special commands
- **Hot Reload** — Update config while the bot is running
- **Windows System Tray** — Minimize to tray with a teal diamond icon
- **PyInstaller Build** — One-click `build.bat` produces a standalone .exe

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy and configure
cp config.example.yml config.yml
# Edit config.yml — set your TikTok username, RCON host/password, etc.

# 3. Run the dashboard
python main.py
```

The dashboard opens at `http://127.0.0.1:5000`. Click "Start Bot" to connect to TikTok Live.

## Configuration

Minimal `config.yml`:

```yaml
Settings:
  TikTokUsername: "@yourstreamer"
  MinecraftUsername: "Steve"

Rcon:
  Host: "127.0.0.1"
  Password: "your_rcon_password"
  Port: 25575

Events:
  Comment:
    - command: chatlog {tag} {user} {mc} {comment}
      type: minecraft
  Follow:
    - command: tntspawn {mc} 10 {user} Follow
      type: minecraft
```

See `config.example.yml` for all gift mappings, VIP lists, and advanced options.

## How It Works

```
TikTok Live ──▶ TikTokLiveClient ──▶ Event Handlers ──▶ RCON Commands ──▶ Minecraft Server
                      │
                Web Dashboard (Flask)
                      │
              Profile YAML configs
```

1. **`minecraftDiamond.py`** — Core bot. Connects to TikTok Live via `TikTokLive`, listens for events, executes RCON commands.
2. **`app.py`** — Flask API & dashboard logic. Manages bot lifecycle, serves web UI.
3. **`main.py`** — Entry point. System tray + subprocess management.
4. **`event_registry.py`** — Dynamic event system with 85+ TikTok events.
5. **`actions.py`** — Action execution engine with context variables.

## Build

```bash
# Windows
build.bat
# Output: dist/TikTokMCIntegrator/
```

Bundles into a single `.exe` with PyInstaller. Templates and static files are embedded.

## Requirements

- Python 3.11+
- Minecraft server with RCON enabled
- TikTok account (public streams)

| Package | Purpose |
| ----- | ----- |
| TikTokLive | TikTok Live connection & events |
| mcrcon | Minecraft RCON protocol |
| Flask + Waitress | Web dashboard |
| spotipy | Spotify song integration |
| pygame | Sound effects |

## Project Structure

```
TikTokMCIntegrator/
├── main.py                 # Entry point + system tray
├── app.py                  # Flask API & dashboard
├── minecraftDiamond.py     # TikTok bot core logic
├── actions.py              # Action execution engine
├── event_registry.py       # 85+ TikTok event definitions
├── constants.py            # Configurable constants
├── utils.py                # JSON helpers
├── badge_helpers.py        # Viewer badge/streak tracking
├── tts_effects.py          # Text-to-speech with effects
├── spotify_handler.py      # Spotify queue & playback
├── config.example.yml      # Example configuration
├── requirements.txt        # Python dependencies
├── build.bat               # Windows build script
├── templates/              # Flask HTML templates
│   ├── index.html          # Main dashboard
│   └── overlay.html        # Stream overlay
├── static/                 # CSS, JS, assets
├── routes/                 # Flask blueprints
│   ├── spotify.py          # Spotify API endpoints
│   └── stats.py            # Stats API endpoints
└── sounds/                 # Audio effects
```

## License

MIT
