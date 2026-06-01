# TikTok Minecraft Integrator - Project Overview

## 📌 Project Summary
This application connects TikTok Live events (gifts, likes, comments) to Minecraft RCON commands. It features a professional web dashboard for configuration and a background bot for live processing.

## 🏗️ Architecture
- **Main Dashboard (`main.py` & `app.py`)**: A Flask-based web server (using Waitress) that provides the user interface.
- **Bot Runner (`minecraftDiamond.py`)**: The core logic that connects to TikTok and sends commands to Minecraft.
- **Native Subprocess Mode**: The dashboard launches the bot using its own executable with the `--run-bot` flag. This eliminates the need for a separate `bot.exe` and fixes issues with "zombie" processes that won't stop.

## 🚀 Key Features & Fixes
- **Real-Time Console**: Uses a global `print()` override with `flush=True` to ensure logs stream instantly to the dashboard.
- **Emoji Support**: Forcefully reconfigures `sys.stdout` to `utf-8` to prevent crashes when viewers have emojis in their nicknames.
- **System Tray Integration**: Runs with a teal diamond icon in the Windows system tray for easy management.
- **Profile Management**: Supports multiple `.yml` profiles stored in the `/profiles` folder.

## 🛠️ Build & Distribution
- **Build Script**: `build.bat` uses PyInstaller to create a standalone folder in `/dist`.
- **Distribution Content**: The `TikTokMCIntegrator_Final.zip` contains:
  - `TikTokMCIntegrator.exe` (The main app)
  - `config.yml` (The default configuration)
  - `available_gifts.json` (List of TikTok gifts for the UI)
  - `profiles/` (Folder for user profiles)
  - `_internal/`, `static/`, `templates/` (Bundled assets)

## 📁 Project Structure
```text
TikTokMCIntegrator/
├── main.py                # Entry point & System Tray
├── app.py                 # Flask API & Dashboard logic
├── minecraftDiamond.py    # TikTok Bot logic (invoked via --run-bot)
├── config.yml             # Global configuration
├── build.bat              # One-click build script
├── profiles/              # User-defined profiles (.yml)
├── static/ & templates/   # Web UI assets
└── dist/                  # Final packaged executables
```

## ⚠️ Important for Future Agents
1. **Piping Output**: Always use `flush=True` for prints in the bot script; otherwise, the dashboard console will appear empty.
2. **Stopping the Bot**: The dashboard uses `bot_process.terminate()` to stop the bot. Since there is no bootloader wrapper, this kills the bot instantly.
3. **Environment**: Ensure `PYTHONUNBUFFERED=1` is set when launching the subprocess to help with log streaming.
