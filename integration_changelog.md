# TikTok-Minecraft Integrator: Development Changelog
**Date:** 2026-04-28

This document outlines the specific architectural changes, stability fixes, and logic overhauls made to the TikTok-to-Minecraft integration script. This log is specifically formatted to provide deep technical context to any future AI agent or developer taking over the codebase.

## 1. Betterproto & TikTokLive `event.user` Crash Resolution
**Problem:** In the newer versions of the `TikTokLive` library, accessing `event.user` triggered a fatal `TypeError` (`User.__init__() got an unexpected keyword argument 'nickName'`). This occurred because the `betterproto` dictionary parser was returning camelCase keys (`nickName`) while the `ExtendedUser` initialization expected snake_case keys (`nick_name`), causing the script to crash entirely upon any user interaction (Comment, Like, Gift, etc.).
**Solution:**
- Implemented a global `get_user(event)` helper function in `minecraftDiamond.py`.
- This helper intercepts the raw protobuf object (`event.user_info`) BEFORE the library attempts to cast it into an `ExtendedUser`, completely bypassing the `betterproto` crash.
- Refactored `on_gift`, `on_like`, `on_comment`, `on_follow`, and `on_subscribe` to use `get_user(event)` instead of `event.user`.
- Safe attribute extraction (`getattr(u, 'nick_name', '')`) is now utilized everywhere to prevent `AttributeError` exceptions.

## 2. Follower & Subscriber (Superfan) Logic Modernization
**Problem:** TikTok updated their platform, replacing traditional Subscriptions with "Superfans" (Fans Club). The old checks (`event.user.is_subscriber` and `event.user.is_follower`) were failing or returning inaccurate data.
**Solution:**
- **Subscriber/Superfan Detection:** Updated the property check to `u.is_subscribe`. Added a robust fallback to check the raw protobuf structure: `u.fans_club_info.fans_level > 0`. This guarantees accurate detection of the new Superfan feature.
- **Follower Detection:** Realized that `u.is_follower` is sometimes missing or unreliable on comment events. Added a fallback mechanism that checks `u.follow_info.follow_status` (where `1` means Following and `2` means Mutual/Friend).

## 3. SuperFanEvent & SubscribeEvent Refactoring
**Problem:** The script relied exclusively on `SuperFanEvent` for subscriptions. However, `SuperFanEvent` inherits from `BarrageEvent` (a system text message), which entirely lacks a `.user` property, causing the script to crash when extracting the user's nickname.
**Solution:**
- Imported and implemented a standard `SubscribeEvent` listener (`@client.on(SubscribeEvent)`), which cleanly provides the `user_info` object for modern subscriptions.
- Kept the `SuperFanEvent` handler as a fallback but rewrote its logic to safely parse the user's nickname dynamically from the barrage text pieces (`event.base_message.display_text.pieces[0].user_value.user.nick_name`). Both events now correctly trigger the `EVENTS.get("SuperFan", [])` Minecraft commands.

## 4. Unicode & Emoji Output Stabilization
**Problem:** The application was fatally crashing (`UnicodeEncodeError: 'charmap' codec can't encode character...`) when viewers with emojis or special font characters in their nicknames interacted with the stream. Additionally, standard output buffering was preventing real-time logs from appearing on the frontend dashboard.
**Solution:**
- Enforced `sys.stdout.reconfigure(encoding='utf-8')` globally.
- Overrode Python's built-in `print()` function globally across the script to forcefully inject `flush=True` into all prints, guaranteeing instant real-time UI updates.
- Wrapped the core `print()` logic in a `try-except UnicodeEncodeError` block. If an unprintable character somehow escapes the UTF-8 parser on Windows, it falls back to encoding to ASCII with `replace` (e.g., swapping emojis with `?`), guaranteeing the bot never crashes over a nickname.

## 5. Architecture & Process Management
**Problem:** The previous setup used multiple conflicting executables, which resulted in "zombie" background processes continuing to run even when the dashboard was closed. Project files were also scattered across the workspace.
**Solution:**
- Restructured the environment into a clean, dedicated `TikTokMCIntegrator/` directory.
- Merged the bot logic and the frontend into a single, unified codebase managed via a `--run-bot` CLI flag. The web dashboard now spawns the exact same executable natively as a subprocess, ensuring perfect cleanup when the main app closes.
- Updated `build.bat` to automatically bundle `config.yml` and the `profiles/` directory into the final distribution package (`TikTokMCIntegrator_Final.zip`), ensuring immediate portability for customers.
