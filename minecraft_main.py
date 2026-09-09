import json
import sys
import builtins
import time
import datetime

# Force stdout to UTF-8 to prevent emoji crashes on Windows
sys.stdout.reconfigure(encoding='utf-8')

# Force all print statements in this file to flush immediately
# This guarantees real-time console logs in the dashboard
_original_print = builtins.print
def print(*args, **kwargs):
    kwargs.setdefault('flush', True)
    try:
        _original_print(*args, **kwargs)
    except UnicodeEncodeError:
        # Ultimate fallback if reconfigure somehow fails
        safe_args = [str(a).encode('ascii', 'replace').decode('ascii') for a in args]
        _original_print(*safe_args, **kwargs)

import asyncio
import math
import requests
import yaml
from collections import deque
import re
import os
from TikTokLive import TikTokLiveClient
from TikTokLive.client.web.web_settings import WebDefaults
from TikTokLive.events import ConnectEvent, CommentEvent, LikeEvent, GiftEvent, FollowEvent, SubNotifyEvent, DisconnectEvent, RoomUserSeqEvent, BarrageEvent, EnvelopeEvent, JoinEvent, LiveEndEvent
from TikTokLive.events.custom_events import SuperFanEvent, SuperFanJoinEvent, SuperFanBoxEvent, UnknownEvent, WebsocketResponseEvent
from mcrcon import MCRcon
from actions import migrate_config_actions, migrate_custom_events_actions, migrate_to_events_redesign, execute_actions as _orig_execute_actions, build_context
from event_registry import EVENT_REGISTRY, get_event_class
import gift_roulette
from gift_delta import GiftDeltaTracker
import gift_catalog
import gift_catalog_sync
import gift_catalog_backfill
import bot_flags
import spotify_handler as sh
from utils import load_json, save_json
from constants import *
from sim_console_log import append_line as append_sim_console_line
import bot_status

# Monkey-patch TikTokLive v7 badge bug (still present in 7.0.0b2):
# _get_all_badge_info() was written for v2
# schema but v3 Schema V3 renamed everything in BadgeStruct:
#   badges → badge_list, badge_scene → scene_type (enum), log_extra → privilege_log_extra
# Without this, member_level, gifter_level, is_moderator, is_top_gifter all return None.
from TikTokLive.proto.custom_proto import ExtendedUser as _ExtendedUser

def _patched_get_all_badge_info(self):
    """v3-aware badge parser. Handles scene_type enum + privilege_log_extra."""
    badge_dict = {}
    # v7 proto field is "badge_list" (was "badges" in v6)
    raw_badges = getattr(self, "badge_list", None) or getattr(self, "badges", None) or []
    for badge in (raw_badges or []):
        # v3: scene_type is an enum (BadgeSceneType), not a string
        scene = getattr(badge, "scene_type", None) or getattr(badge, "badge_scene", None)
        if scene is None:
            continue
        # Get enum name (e.g. "FANS", "SUBSCRIBER", "USER_GRADE")
        # betterproto2 enums: str() → "BadgeSceneType.FANS", .name → "FANS" if IntEnum
        scene_name = getattr(scene, "name", None) or str(scene)
        scene_name = str(scene_name).replace("BADGE_SCENE_TYPE_", "").upper()
        # Strip class prefix if present (e.g. "BADGESCENETYPE.FANS" → "FANS")
        if "." in scene_name:
            scene_name = scene_name.rsplit(".", 1)[-1]

        # v3: privilege_log_extra (was log_extra), level is a string
        log_extra = getattr(badge, "privilege_log_extra", None) or getattr(badge, "log_extra", None)
        badge_level = getattr(log_extra, "level", None) if log_extra else None
        if badge_level is not None:
            try:
                badge_level = str(badge_level)  # v3 returns str, v6 returned int
            except Exception:
                continue
        if scene_name and badge_level:
            if scene_name not in badge_dict:
                badge_dict[scene_name] = badge_level
    return list(badge_dict.items())

_ExtendedUser._get_all_badge_info = _patched_get_all_badge_info

def _extract_badge_icons(user) -> list:
    """
    Extract all badges with type, level, icon URL, and level text from user.badge_list.
    Returns: [{"type": "FANS", "level": 5, "icon": "https://...", "level_text": "5", "bg_color": "#xxx", "border_color": "#xxx"}, ...]
    """
    from badge_helpers import (
        _extract_scene_type, _extract_badge_level,
        _extract_combine_icon, _extract_combine_text, _extract_combine_colors,
        _extract_image_icon,
    )

    badges = []
    raw_badges = getattr(user, "badge_list", None) or getattr(user, "badges", None) or []
    for badge in (raw_badges or []):
        # Get scene type (badge category)
        scene_name = _extract_scene_type(badge)
        if not scene_name:
            continue

        # Get level from privilege_log_extra
        badge_level = _extract_badge_level(badge)

        icon_url = ""
        level_text = ""
        bg_color = ""
        border_color = ""

        # COMBINE type: icon + text + background (most common for level badges)
        combine = getattr(badge, "combine", None)
        if combine:
            icon_url = _extract_combine_icon(combine)
            level_text = _extract_combine_text(combine)
            bg_color, border_color = _extract_combine_colors(combine)

        # IMAGE type: just an icon (fallback)
        if not icon_url:
            icon_url = _extract_image_icon(badge)

        badges.append({
            "type": scene_name,
            "level": badge_level,
            "icon": icon_url,
            "level_text": level_text,
            "bg_color": bg_color,
            "border_color": border_color
        })

    return badges

# ==========================================
# LOAD CONFIGURATION
# ==========================================
# Centralized path layout (config/ data/ logs/ assets/) — single frozen-aware root.
import paths
from avatar_cache import cache_avatar_image, is_local_avatar_url
BASE_DIR = paths.BASE_DIR
CONFIG_FILE = paths.config("config.yml")
SUPERFAN_DEBUG_LOG = paths.logs("superfan_debug.log")
RELOAD_SIGNAL_FILE = os.path.join(paths.DATA_DIR, ".reload_signal")


def _is_debug_mode_enabled() -> bool:
    """Live-read Settings.DebugMode from config.yml. Default: False.

    When OFF, the SuperFan/WebSocket event probes write nothing — this is what
    stops superfan_debug.log from ballooning (it records every TikTok WS event).
    Live-read so the dashboard toggle takes effect mid-stream with no restart.
    """
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                c = yaml.safe_load(f) or {}
            return bool(c.get("Settings", {}).get("DebugMode", False))
    except Exception:
        pass
    return False

def _is_log_only_mode_enabled() -> bool:
    """Live-read Settings.LogOnlyMode from config.yml. Default: False.

    When ON, ALL events fire and are logged exactly as normal, but NO actions
    execute (no Minecraft commands, no sounds, no webhooks, no overlays).
    The dashboard shows \"DEBUG MODE\" to indicate this mode.
    """
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                c = yaml.safe_load(f) or {}
            return bool(c.get("Settings", {}).get("LogOnlyMode", False))
    except Exception:
        pass
    return False

def _should_skip_action_execution() -> bool:
    """Return True if LogOnlyMode is ON."""
    return _is_log_only_mode_enabled()


async def execute_actions(actions, context=None, send_mc_command=None):
    """Execute a list of actions in order — skip everything if LogOnlyMode is ON."""
    if _should_skip_action_execution():
        return  # Skip execution entirely; events already log what was skipped
    return await _orig_execute_actions(actions, context, send_mc_command)

if _is_debug_mode_enabled():
    try:
        with open(SUPERFAN_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat()} SUPERFAN_DEBUG_INIT base_dir={BASE_DIR}\n")
    except Exception:
        pass

if not os.path.exists(CONFIG_FILE):
    print(f"Error: {CONFIG_FILE} not found. Please create one from the template.")
    exit(1)

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# Extract Main Settings
TIKTOK_USERNAME = config.get("Settings", {}).get("TikTokUsername", "")
MC_USERNAME = config.get("Settings", {}).get("MinecraftUsername", "")
EULER_API_KEY=config.get("Settings", {}).get("EulerApiKey", "")

RCON_HOST = config.get("Rcon", {}).get("Host", "127.0.0.1")
RCON_PASSWORD=config.get("Rcon", {}).get("Password", "")
RCON_PORT = config.get("Rcon", {}).get("Port", 25575)

# Gift asset downloader (opt-in): caches 100+ coin gift animation assets to disk.
# Uses a function so config changes from the UI apply immediately (no restart).
def _is_gift_downloader_enabled() -> bool:
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                c = yaml.safe_load(f) or {}
            return bool(c.get("Settings", {}).get("GiftAssetDownloader", False))
    except Exception:
        pass
    return False


# Gift catalog region sync (default ON): unions EulerStream's per-region gift
# panels into available_gifts.json so region-locked gifts get a name, price and
# icon in the dashboard. Read per call so the UI toggle applies without a
# restart, matching the project rule for live settings.
def _is_gift_region_sync_enabled() -> bool:
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                c = yaml.safe_load(f) or {}
            return bool(c.get("Settings", {}).get("GiftCatalogRegionSync", True))
    except Exception:
        pass
    return True


def _current_euler_api_key() -> str:
    """Euler key read live, so a key pasted into the UI works without restart."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                c = yaml.safe_load(f) or {}
            return str(c.get("Settings", {}).get("EulerApiKey", "") or "")
    except Exception:
        pass
    return EULER_API_KEY


def _sync_gift_regions_once():
    """Blocking region + full-catalog sync; always called via asyncio.to_thread."""
    try:
        path = paths.data("available_gifts.json")
        key = _current_euler_api_key()

        regions = gift_catalog_sync.sync_regions(path, key)
        if regions.get("error"):
            print(f"[GIFT-CATALOG] Region sync skipped: {regions['error']}")
        else:
            print(
                f"[GIFT-CATALOG] Region sync: {regions['regions_ok']} regions ok, "
                f"{regions['regions_failed']} failed (+{regions['added']} new, "
                f"{regions['updated']} updated)"
            )

        catalog = gift_catalog_sync.sync_euler_catalog(path, key)
        if catalog.get("error"):
            print(f"[GIFT-CATALOG] Full catalog sync: {catalog['error']}")
        else:
            print(
                f"[GIFT-CATALOG] Full catalog: {catalog['fetched']} rows over "
                f"{catalog['pages']} pages (+{catalog['added']} new, "
                f"{catalog['updated']} updated)"
            )

        history = gift_catalog_backfill.backfill_all(
            path, paths.data("gift_log.json"), paths.data("points.db")
        )
        if history["added"] or history["updated"]:
            print(
                f"[GIFT-CATALOG] History backfill: +{history['added']} new, "
                f"{history['updated']} updated"
            )

        print(f"[GIFT-CATALOG] Catalog now holds {len(gift_catalog.load_catalog(path))} gifts")
    except Exception as e:
        print(f"[GIFT-CATALOG] Catalog sync failed: {e}")

# Extract Data
VIP_LIST = set(config.get("VIP_List", []))
GIFTS_WITH_STREAK_DELTA = set(config.get("StreakDeltaGifts", []))
# Chat filter: list of allowed user categories (empty = show all)
# Valid: vip, superfan, member, friend, follower, newbie
CHAT_FILTER = set(config.get("ChatFilter", []))
# Chat filter: minimum levels (0 = no filter)
CHAT_FILTER_MIN_GIFTER_LEVEL = config.get("ChatFilterMinGifterLevel", 0)
CHAT_FILTER_MIN_MEMBER_LEVEL = config.get("ChatFilterMinMemberLevel", 0)

# Auto-convert old-format (string lists) to new-format (typed action dicts)
config = migrate_config_actions(config)
config = migrate_custom_events_actions(config)
# Migrate to Events redesign (GlobalCommands/Likes/CustomEvents → Events/Gifts.GlobalActions)
config = migrate_to_events_redesign(config)

GIFT_ACTIONS = config.get("Gifts", {})

# Gift Roulette — normalized config snapshot (plan: .hermes/plans/roulette-randomizer.md).
# Never parsed per gift event: re-normalized only at startup and on hot-reload,
# exactly like GIFT_ACTIONS. Saving in the dashboard applies live via signal_reload.
ROULETTE_CONFIG = gift_roulette.normalize_config(config.get("Roulette"))
# Roulette display snapshots: GiftNames + GiftDescriptions for reel labels.
ROULETTE_NAMES = dict(config.get("GiftNames", {}) or {})
ROULETTE_DESCRIPTIONS = dict(config.get("GiftDescriptions", {}) or {})
# Stale spinning state from a prior process is cancelled, never replayed.
ROULETTE_RUNTIME = gift_roulette.RouletteRuntime(paths.data("roulette_state.json"))
try:
    if ROULETTE_RUNTIME.sweep_stale():
        print("[ROULETTE] Cancelled stale spinning state from a prior process.")
except Exception as rl_err:
    print(f"[ROULETTE] Stale-state sweep failed: {rl_err}")

# Skip cooldown to prevent double-skips
_last_skip_time = 0
SKIP_COOLDOWN = 3  # seconds between skips
EVENTS = config.get("Events", {})
# Remove old-style keys if they still exist after migration
GLOBAL_COMMANDS = config.get("GlobalCommands", {})
CUSTOM_EVENTS = config.get("CustomEvents", {})

# ── Dynamic Event Registration ───────────────────────────────────────────────
# Track registered dynamic listeners so we can remove them on hot-reload
_dynamic_listeners = []

def _make_dynamic_handler(event_key, reg_entry):
    """Factory function to create a handler for a dynamic event.

    Uses closure over event_key and reg_entry to avoid the classic loop-variable bug.
    """
    async def handler(event):
        try:
            template_vars = reg_entry.get("template_vars", ["user", "mc", "amount"])
            ctx = build_context(event, template_vars, mc_username=MC_USERNAME, vip_list=VIP_LIST)
            actions = EVENTS.get(event_key, [])
            # Events can be a dict (Like event with mode/interval/actions) or a list
            if isinstance(actions, dict):
                actions = actions.get("actions", [])
            if actions and not _should_skip_action_execution():
                await execute_actions(actions, ctx, send_minecraft_command)
            elif actions and _should_skip_action_execution():
                print(f"[LOG-ONLY] Skipping execution of {len(actions)} action(s) for {event_key}")
        except Exception as e:
            print(f"[DYNAMIC] Error in {event_key} handler: {e}")
    return handler


def register_dynamic_events():
    """Register all enabled events from config dynamically.

    This is called at startup and after hot-reload to re-register event listeners.
    """
    global _dynamic_listeners

    # First, remove previously registered dynamic listeners
    for entry in _dynamic_listeners:
        try:
            client.remove_listener(entry["event"], entry["handler"])
        except Exception:
            pass
    _dynamic_listeners.clear()

    # Register new listeners for all Events that have actions configured
    registered_count = 0
    for event_key, actions in EVENTS.items():
        # Actions can be a list or a dict (Like: {mode, interval, actions})
        if isinstance(actions, dict):
            action_list = actions.get("actions", [])
        else:
            action_list = actions
        if not action_list:
            continue

        event_class = get_event_class(event_key)
        if event_class is None:
            # Like_* keys are handled by the hard-coded on_like handler
            if not event_key.startswith("Like"):
                print(f"[DYNAMIC] Unknown event key: {event_key}, skipping")
            continue

        # Skip infrastructure events (handled by hard-coded handlers)
        reg_entry = EVENT_REGISTRY.get(event_key, {})
        if reg_entry.get("infra", False):
            print(f"[DYNAMIC] Skipping infrastructure event: {event_key}")
            continue

        handler = _make_dynamic_handler(event_key, reg_entry)
        client.add_listener(event_class, handler)
        _dynamic_listeners.append({"event": event_class, "handler": handler})
        registered_count += 1

    if registered_count > 0:
        print(f"[DYNAMIC] Registered {registered_count} dynamic event handler(s).")

# Hot-reloadable globals (re-read from config on signal)
def reload_config():
    """Hot-reload config changes without restarting the bot. Only non-critical settings."""
    global VIP_LIST, GIFTS_WITH_STREAK_DELTA, GIFT_ACTIONS, EVENTS, GLOBAL_COMMANDS, CUSTOM_EVENTS, CHAT_FILTER, CHAT_FILTER_MIN_GIFTER_LEVEL, CHAT_FILTER_MIN_MEMBER_LEVEL, ROULETTE_CONFIG, ROULETTE_NAMES, ROULETTE_DESCRIPTIONS
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        VIP_LIST = set(config.get("VIP_List", []))
        GIFTS_WITH_STREAK_DELTA = set(config.get("StreakDeltaGifts", []))
        CHAT_FILTER = set(config.get("ChatFilter", []))
        CHAT_FILTER_MIN_GIFTER_LEVEL = config.get("ChatFilterMinGifterLevel", 0)
        CHAT_FILTER_MIN_MEMBER_LEVEL = config.get("ChatFilterMinMemberLevel", 0)
        # Auto-convert old-format to new-format
        config = migrate_config_actions(config)
        config = migrate_custom_events_actions(config)
        config = migrate_to_events_redesign(config)
        GIFT_ACTIONS = config.get("Gifts", {})
        ROULETTE_CONFIG = gift_roulette.normalize_config(config.get("Roulette"))
        # Roulette display names: GiftNames/GiftDescriptions snapshots for the
        # reel labels — hot-reloaded with everything else.
        ROULETTE_NAMES = dict(config.get("GiftNames", {}) or {})
        ROULETTE_DESCRIPTIONS = dict(config.get("GiftDescriptions", {}) or {})
        EVENTS = config.get("Events", {})
        GLOBAL_COMMANDS = config.get("GlobalCommands", {})
        CUSTOM_EVENTS = config.get("CustomEvents", {})
        # Re-register dynamic event handlers
        register_dynamic_events()
        print(f"[HOT-RELOAD] Config reloaded successfully.")
    except Exception as e:
        print(f"[HOT-RELOAD] Failed to reload config: {e}")

async def config_watcher():
    """Periodically check for hot-reload signal from the dashboard."""
    while True:
        if os.path.exists(RELOAD_SIGNAL_FILE):
            reload_config()
            try:
                os.remove(RELOAD_SIGNAL_FILE)
            except Exception:
                pass
        await asyncio.sleep(3)

# Initialize Client
client: TikTokLiveClient = TikTokLiveClient(unique_id=TIKTOK_USERNAME)
from reconnect_diagnostics import install_http_response_capture
install_http_response_capture(client.web.httpx_client)
WebDefaults.tiktok_sign_api_key = EULER_API_KEY
# 2026-06-09 EulerStream notice: /webcast/anchors/{unique_id}/room_id and
# /webcast/bulk_live_check temporarily broken on primary host; legacy host works.
WebDefaults.tiktok_sign_url = "https://tiktok-legacy.eulerstream.com"

# ==========================================
# SIMULATED MINECRAFT CONSOLE (always-on log)
# ==========================================
# Captures every command sent + response for the Sim Console UI panel.
# Independent of the bot's stdout log — useful when running single-player
# (no real server console) or just for debugging.
# The bot writes here, the dashboard reads it from a file so both
# processes (separate PyInstaller exe sub-processes) can share state.
SIM_CONSOLE_LOG: deque = deque(maxlen=500)

def _sim_console_push(line: str) -> None:
    """Append a timestamped line to the simulated console log (in-memory + file)."""
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {line}"
    SIM_CONSOLE_LOG.append(entry)
    # Also write to a file the dashboard can read without importing us
    try:
        log_path = paths.logs("sim_console.log")
        append_sim_console_line(log_path, entry)
    except Exception:
        pass

# ==========================================
# CONNECTOR CONFIG (live-read)
# ==========================================
def _get_connector_type() -> str:
    """Live-read Settings.ConnectorType from config.yml. Default: rcon."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                c = yaml.safe_load(f) or {}
            v = c.get("Settings", {}).get("ConnectorType", "rcon")
            return v if v in ("rcon", "forge", "servertap") else "rcon"
    except Exception:
        pass
    return "rcon"

def _get_forge_config() -> dict:
    """Live-read Forge block from config.yml. Defaults: 127.0.0.1:5942."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                c = yaml.safe_load(f) or {}
            f = c.get("Forge", {}) or {}
            return {
                "host": str(f.get("Host", "127.0.0.1")),
                "port": int(f.get("Port", 5942)),
                "password": str(f.get("Password", "")),
            }
    except Exception:
        pass
    return {"host": "127.0.0.1", "port": 5942, "password": ""}


def _get_servertap_config() -> dict:
    """Live-read ServerTap block from config.yml. Defaults: 127.0.0.1:4567."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                c = yaml.safe_load(f) or {}
            s = c.get("ServerTap", {}) or {}
            return {
                "host": str(s.get("Host", "127.0.0.1")),
                "port": int(s.get("Port", 4567)),
                "api_key": str(s.get("ApiKey", "")),
            }
    except Exception:
        pass
    return {"host": "127.0.0.1", "port": 4567, "api_key": ""}


# ==========================================
# RCON HELPER (legacy connector)
# ==========================================
def __send_rcon_command(command):
    try:
        with MCRcon(RCON_HOST, RCON_PASSWORD, port=RCON_PORT) as mcr:
            response = mcr.command(command)
            if response:
                _sim_console_push(response)
    except Exception as e:
        _sim_console_push(f"[ERR] RCON: {e}")
        print(f"Failed to send RCON command '{command}': {e}")

# ==========================================
# FORGE MOD CONNECTOR (single-player)
# ==========================================
def __send_forge_command(command):
    cfg = _get_forge_config()
    _sim_console_push(f"[→] {command}")
    try:
        r = requests.post(
            f"http://{cfg['host']}:{cfg['port']}/command",
            json={"password": cfg["password"], "command": command},
            timeout=RCON_TIMEOUT,
        )
        if r.status_code == 200:
            try:
                data = r.json()
                output = data.get("output", "")
                if output:
                    _sim_console_push(output)
                else:
                    _sim_console_push("[ok]")
            except Exception:
                _sim_console_push(f"[ok] {r.text[:200]}")
        else:
            _sim_console_push(f"[ERR] HTTP {r.status_code}: {r.text[:200]}")
    except requests.exceptions.ConnectionError:
        _sim_console_push(f"[ERR] forge mod unreachable at {cfg['host']}:{cfg['port']} (is MC running with the mod?)")
    except Exception as e:
        _sim_console_push(f"[ERR] forge: {e}")
        print(f"Failed to send forge command '{command}': {e}")

# ==========================================
# DISPATCHER
# ==========================================
def __send_sync_command(command):
    """Dispatch to active connector (RCON, Forge mod, or ServerTap)."""
    _sim_console_push(f"[→] {command}")
    ctype = _get_connector_type()
    if ctype == "servertap":
        __send_servertap_command(command)
    elif ctype == "forge":
        __send_forge_command(command)
    else:
        __send_rcon_command(command)


# ==========================================
# SERVERTAP CONNECTOR (Paper/Spigot REST API)
# ==========================================
def __send_servertap_command(command):
    """Send command via ServerTap REST API (TikFinity backend)."""
    cfg = _get_servertap_config()
    _sim_console_push(f"[→] {command}")
    try:
        # ServerTap uses POST to /execute with JSON body
        # Endpoint: http://host:port/api/execute
        r = requests.post(
            f"http://{cfg['host']}:{cfg['port']}/api/execute",
            json={
                "apiKey": cfg["api_key"],
                "command": command
            },
            timeout=RCON_TIMEOUT,
        )
        if r.status_code == 200:
            try:
                data = r.json()
                output = data.get("output", "") or data.get("response", "")
                if output:
                    _sim_console_push(output)
                else:
                    _sim_console_push("[ok]")
            except Exception:
                _sim_console_push(f"[ok] {r.text[:200]}")
        elif r.status_code == 401:
            _sim_console_push(f"[ERR] ServerTap auth failed - check ApiKey in config")
        else:
            _sim_console_push(f"[ERR] HTTP {r.status_code}: {r.text[:200]}")
    except requests.exceptions.ConnectionError:
        _sim_console_push(f"[ERR] ServerTap unreachable at {cfg['host']}:{cfg['port']} (is ServerTap plugin installed?)")
    except Exception as e:
        _sim_console_push(f"[ERR] servertap: {e}")
        print(f"Failed to send servertap command '{command}': {e}")

async def send_minecraft_command(command):
    """Fire a Minecraft command immediately without awaiting connector I/O.

    Each command gets its own daemon thread. This deliberately bypasses asyncio's
    shared thread-pool queue and does not hold the TikTok event handler open while
    RCON connects, executes, or waits for the server response.
    """
    _threading.Thread(
        target=__send_sync_command,
        args=(command,),
        daemon=True,
        name="minecraft-command",
    ).start()


# ==========================================
# HELPERS
# ==========================================
def mc_safe(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\n", " ").replace("\r", " ")
    for ch in ['\'', '"', ';', '(', ')', '{', '}']:
        s = s.replace(ch, "")
    return s

def get_gift_icon(gift_id):
    """Lookup gift icon URL from the union-merged available_gifts.json cache."""
    try:
        return gift_catalog.icon_for(paths.data("available_gifts.json"), gift_id)
    except Exception:
        return ""


def learn_gift_from_event(gift, gift_id, gift_name, diamond_count):
    """Teach the catalog a gift straight off a live GiftEvent.

    TikTok's /gift/list/ only returns the room panel (verified: 701 of 2783
    gifts, is_full_gift_data=False), so creator/event-exclusive gifts such as
    Super GG (12988) and KhitoFam (938882) are in NO catalog anywhere — the
    GiftEvent itself is the only place their icon and price ever appear. Without
    this, those gifts render with a blank icon forever.
    """
    try:
        icon_url = _image_url_from_model(getattr(gift, "icon", None)) \
            or _image_url_from_model(getattr(gift, "image", None))
        if gift_catalog.learn_gift(
            paths.data("available_gifts.json"),
            gift_id=gift_id,
            name=gift_name,
            diamond_count=diamond_count,
            icon_url=icon_url,
        ):
            print(f"[GIFT-CATALOG] Learned '{gift_name}' (id={gift_id}, {diamond_count} coins) from live event")
    except Exception as e:
        print(f"[GIFT-CATALOG] Could not learn gift {gift_id}: {e}")

def get_gift_tier(total_coins):
    """Calculate visual tier based on total coin value."""
    if total_coins >= 10000:
        return 5
    elif total_coins >= 1000:
        return 4
    elif total_coins >= 500:
        return 3
    elif total_coins >= 100:
        return 2
    return 1

def append_gift_log(gift_id, gift_name, sender, repeat_count, total_coins, diamond_count=0, asset_url="", asset_pending=False):
    """Append a gift event to the rolling gift log for the dashboard/overlays."""
    try:
        asset_key = f"{int(time.time() * 1000)}-{gift_id}-{abs(hash((sender, gift_name, repeat_count, total_coins))) % 1000000}"
        entry = {
            "gift_id": str(gift_id),
            "gift_name": gift_name,
            "icon": get_gift_icon(gift_id),
            "sender": sender,
            "repeat_count": repeat_count,
            "diamond_count": diamond_count,
            "total_coins": total_coins,
            "tier": get_gift_tier(total_coins),
            "timestamp": time.monotonic(),
            "asset_key": asset_key,
        }
        if asset_url:
            entry["asset_url"] = asset_url
        if asset_pending:
            entry["asset_pending"] = True
        _buffer_append(paths.data("gift_log.json"), entry)
        return asset_key
    except Exception as e:
        print(f"Error writing gift log: {e}")
        return None


def update_gift_log_asset(asset_key, local_url):
    """Attach a downloaded animation URL to an existing gift-log entry."""
    if not asset_key or not local_url:
        return False
    log_file = paths.data("gift_log.json")
    updated = False
    try:
        with _log_buffer_lock:
            entries = _log_buffers.get(log_file)
            if not isinstance(entries, list):
                entries = load_json(log_file, [])
                if not isinstance(entries, list):
                    entries = []
                _log_buffers[log_file] = entries
            for entry in reversed(entries):
                if isinstance(entry, dict) and entry.get("asset_key") == asset_key:
                    entry["asset_url"] = local_url
                    entry["asset_pending"] = False
                    updated = True
                    break
            if updated:
                _log_dirty.add(log_file)
        if updated:
            print(f"[GIFT-ASSET] Attached animation to gift log: {local_url}")
            try:
                _flush_buffers_once()
            except Exception:
                pass
            return True
        print(f"[GIFT-ASSET] Could not find gift log entry for asset_key={asset_key}")
    except Exception as e:
        print(f"[GIFT-ASSET] Error updating gift log asset: {e}")
    return False


def _asset_url_list(resource_model):
    """Return URL candidates from a TikTok resource model, safest first."""
    if not resource_model:
        return []
    urls = getattr(resource_model, "url_list", None) or []
    return [str(u) for u in urls if u]


def _gift_asset_source_urls(event):
    """Extract possible animated gift asset URLs from GiftEvent variants.

    TikTok does not always put the playable animation in event.asset.resource_url.
    Some rooms/gifts expose HEVC/bytevc1 URLs, video_resource_list, or asset_bundle.
    Keep this resolver broad so topgift can animate when connected to any streamer.
    """
    urls = []

    def add_resource(resource_model):
        for url in _asset_url_list(resource_model):
            if url not in urls:
                urls.append(url)

    def add_asset(asset):
        if not asset:
            return
        # Prefer browser-playable MP4/WebM resources over bytevc1/HEVC fallback.
        add_resource(getattr(asset, "resource_url", None))
        for vr in (getattr(asset, "video_resource_list", None) or []):
            add_resource(getattr(vr, "video_url", None))
        add_resource(getattr(asset, "resource_bytevc1_url", None))

    add_asset(getattr(event, "asset", None))

    bundle = getattr(event, "asset_bundle", None)
    for asset in (getattr(bundle, "assets", None) or []):
        add_asset(asset)

    return urls


def start_gift_asset_download(asset_key, gift_id, source_urls):
    """Download a gift animation off the event loop, then update the gift log."""
    if not asset_key or not gift_id or not source_urls:
        return
    if isinstance(source_urls, str):
        source_urls = [source_urls]
    source_urls = [u for u in source_urls if u]

    def _worker():
        try:
            from assets.gift_assets.downloader import download_gift_asset
            local = None
            for source_url in source_urls:
                local = download_gift_asset(int(gift_id), source_url, timeout=5)
                if local:
                    break
            if local:
                update_gift_log_asset(asset_key, local)
            else:
                print(f"[GIFT-ASSET] No downloadable animation worked for gift_id={gift_id} ({len(source_urls)} candidate URLs)")
        except Exception as e:
            print(f"[GIFT-ASSET] Background download error for gift_id={gift_id}: {e}")

    try:
        t = _threading.Thread(target=_worker, daemon=True, name=f"gift-asset-{gift_id}")
        t.start()
    except Exception as e:
        print(f"[GIFT-ASSET] Could not start downloader thread for gift_id={gift_id}: {e}")

def append_follow_log(nick, unique_id, avatar_url=""):
    """Append a follow event to the rolling follow log for the dashboard."""
    try:
        _buffer_append(paths.data("follow_log.json"), {
            "nick": nick,
            "unique_id": unique_id,
            "avatar_url": avatar_url,
            "timestamp": time.monotonic()
        })
    except Exception as e:
        print(f"Error writing follow log: {e}")

def append_chat_log(nick, unique_id, comment, tags, avatar_url="", badges=None, gifter_level=0, member_level=0):
    """Log chat messages to chat_log.json for post-stream reports."""
    try:
        entry = {
            "nick": nick,
            "unique_id": unique_id,
            "comment": comment,
            "tags": tags,
            "avatar_url": avatar_url,
            "gifter_level": gifter_level,
            "member_level": member_level,
            "timestamp": time.monotonic()
        }
        if badges:
            entry["badges"] = badges
        _buffer_append(paths.data("chat_log.json"), entry)
    except Exception as e:
        print(f"Error writing chat log: {e}")

# ==========================================
def append_superfan_log(nick, event_type="new_superfan", unique_id="", avatar_url="", tags="", badges=None, extra=None):
    """Log superfan events to superfan_log.json for dashboard + overlay."""
    if event_type in ("superfan_join", "superfan_join_ignored") and (not nick or nick == "Someone") and not unique_id:
        return
    try:
        entry = {
            "nick": nick,
            "unique_id": unique_id,
            "avatar_url": avatar_url,
            "tags": tags,
            "badges": badges or [],
            "event_type": event_type,
            "timestamp": time.monotonic()
        }
        if isinstance(extra, dict):
            entry.update({k: v for k, v in extra.items() if v not in (None, "")})
        _buffer_append(paths.data("superfan_log.json"), entry)
    except Exception as e:
        print(f"Error writing superfan log: {e}")

# EVENT HANDLERS (v7 — TikTokLive 7.0.0b2)
# ==========================================

@client.on(ConnectEvent)
async def on_connect(event: ConnectEvent):
    print(f"Connected to @{event.unique_id} (Room ID: {client.room_id})")
    bot_status.write_status(paths, "connected", room_id=str(client.room_id or ""), username=event.unique_id)

    # Check if this is a reconnect to the same stream
    is_reconnect = False
    try:
        prev_state = load_json(paths.data("stream_state.json"), {})
        if prev_state.get("room_id") == client.room_id:
            is_reconnect = True
            print(f"[RECONNECT] Same room — preserving stream data.")
    except Exception:
        pass

    # Start the background log-flush thread (off the event loop). Idempotent.
    _start_log_flusher()

    if not is_reconnect:
        # Fresh session — reset buffers AND on-disk files.
        for log_file in ["gift_log.json", "follow_log.json", "chat_log.json", "superfan_log.json"]:
            _buffer_clear(paths.data(log_file), [])
        try:
            save_json(paths.data("active_streaks.json"), {})
        except Exception:
            pass

        # Clear in-memory active streaks
        active_streaks.clear()
        streak_tracker.clear()

        # Clear stale viewer stats from previous session
        save_json(paths.data("viewer_stats.json"), {"viewers": 0, "total_viewers": 0, "updated_at": asyncio.get_event_loop().time()})

        # Fresh live -> clear the Top Gifters / Top Likers leaderboards.
        try:
            stream_ranking.reset(GIFTER_RANKING_FILE)
            stream_ranking.reset(LIKER_RANKING_FILE)
        except Exception:
            pass
    else:
        # Reconnect — load preserved on-disk entries into the buffers so the
        # flush thread doesn't overwrite them with an empty array.
        for log_file in ["gift_log.json", "follow_log.json", "chat_log.json", "superfan_log.json"]:
            _buffer_init(paths.data(log_file), [])
        # Reconnect -> reload the leaderboards preserved on disk.
        try:
            stream_ranking.init_from_disk(GIFTER_RANKING_FILE)
            stream_ranking.init_from_disk(LIKER_RANKING_FILE)
        except Exception:
            pass

    # Baseline any leftover manual-reset token from a previous live so it
    # doesn't wipe this live's first entries.
    try:
        stream_ranking.ack_reset_token()
    except Exception:
        pass

    # Write stream state for report generation
    stream_state = {
        "room_id": client.room_id,
        "started_at": datetime.datetime.now().isoformat(),
        "username": event.unique_id
    }
    save_json(paths.data("stream_state.json"), stream_state)

    # Start config watcher for hot-reload (event loop is running now)
    asyncio.ensure_future(config_watcher())

    # Register any dynamic custom events from config
    register_dynamic_events()

    # Merge the room's gift panel into the union catalog for the UI.
    #
    # TikTok's panel is NOT the full catalog: it self-reports
    # is_full_gift_data=False and returned 701 of the 2783 known gifts on
    # Khito's room (verified 2026-09-02). The old code overwrote
    # available_gifts.json wholesale here, which deleted every gift the app had
    # learned from live events or a region sync. Merge, never replace.
    try:
        if hasattr(client, "gift_info") and isinstance(client.gift_info, dict) and "gifts" in client.gift_info:
            panel = client.gift_info["gifts"]
            stats = gift_catalog.merge_into_catalog(
                paths.data("available_gifts.json"), panel, source="panel"
            )
            # Re-evaluate panel truth against THIS fetch: gifts that rotated out
            # of TikTok's panel lose in_panel (they stay in the full catalog and
            # stay 'seen' if ever received). Keeps the room-scope picker honest.
            flipped = gift_catalog.mark_panel_gifts(
                paths.data("available_gifts.json"),
                [g.get("id") for g in panel if isinstance(g, dict) and g.get("id")],
            )
            total = len(gift_catalog.load_catalog(paths.data("available_gifts.json")))
            print(
                f"[GIFT-CATALOG] Room panel: {len(panel)} gifts "
                f"(+{stats['added']} new, {stats['updated']} updated, "
                f"{flipped} panel flags changed) -> catalog now {total}"
            )
    except Exception as e:
        print(f"Error merging room gift panel into catalog: {e}")

    # Region sync backfills gifts TikTok hides from this room's panel — e.g.
    # Game Controller (6581/7569, 100 coins) exists in the US panel but not
    # Indonesia's. Runs off-loop so it never delays the connect path.
    try:
        if _is_gift_region_sync_enabled():
            asyncio.create_task(asyncio.to_thread(_sync_gift_regions_once))
    except Exception as e:
        print(f"[GIFT-CATALOG] Could not start region sync: {e}")

@client.on(DisconnectEvent)
async def on_disconnect(event: DisconnectEvent):
    print(f"Disconnected. Room ID was: {client.room_id or 'N/A'}")
    bot_status.write_status(paths, "disconnected", room_id=str(client.room_id or ""))
    # Flush any buffered events to disk immediately so nothing is lost on a drop.
    try:
        _flush_buffers_once()
    except Exception:
        pass
    # Zero out viewer stats so dashboard doesn't show stale data
    with open(paths.data("viewer_stats.json"), "w", encoding="utf-8") as f:
        json.dump({"viewers": 0, "total_viewers": 0, "updated_at": asyncio.get_event_loop().time()}, f)

@client.on(LiveEndEvent)
async def on_live_end(event: LiveEndEvent):
    """The streamer actually ENDED the live. This is a clean stop, not a drop —
    set the flag so run_bot() exits instead of trying to reconnect."""
    global _stream_ended_cleanly
    _stream_ended_cleanly = True
    print("Live ended by streamer. Bot will stop (no reconnect).", flush=True)
    bot_status.write_status(paths, "ended", room_id=str(client.room_id or ""))
    try:
        _flush_buffers_once()
    except Exception:
        pass
    try:
        # Persist final leaderboard state (likes flush at most 1x/sec in-memory).
        stream_ranking.flush_all()
    except Exception:
        pass
    streak_tracker.clear()

@client.on(RoomUserSeqEvent)
async def on_room_user_seq(event: RoomUserSeqEvent):
    """Handle viewer count updates and write to JSON for the dashboard."""
    try:
        stats = {
            "viewers": getattr(event, 'total', 0),
            "total_viewers": getattr(event, 'total_user', 0),
            "updated_at": asyncio.get_event_loop().time()
        }
        with open(paths.data("viewer_stats.json"), "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
    except Exception as e:
        print(f"Error writing viewer stats: {e}")


# Tracking Delta Streaks
streak_tracker = GiftDeltaTracker(ended_ttl_seconds=30)

# File write lock — prevents race conditions on JSON logs
import threading as _threading
_log_lock = _threading.Lock()


def _active_profile_name() -> str:
    """Active profile name for Roulette state tagging (diagnostics only)."""
    try:
        return (paths.config("active_profile.txt") and open(
            paths.config("active_profile.txt"), "r", encoding="utf-8"
        ).read().strip()) or "default"
    except Exception:
        return "default"


def _log_roulette_task_done(task) -> None:
    """Surface unexpected background spin-task crashes without raising."""
    try:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            print(f"[ROULETTE] Spin task failed: {exc}")
    except Exception:
        pass


def safe_json_write(data, log_file, retries=3, delay=0.05):
    """Write JSON to file atomically with retry on Windows file lock errors."""
    tmp_file = log_file + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    for attempt in range(retries):
        try:
            os.replace(tmp_file, log_file)
            return
        except OSError as e:
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                # Last resort: try direct write instead of rename
                try:
                    with open(log_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                except Exception:
                    pass
                print(f"Atomic write failed after {retries} attempts: {e}")


# ==========================================
# IN-MEMORY LOG BUFFERS (event-loop safety)
# ==========================================
# The bot's TikTok event handlers run on the asyncio event loop. The old code
# did a synchronous read-modify-write of the ENTIRE json log file PER message
# (O(N) per event, O(N^2) over a stream). On a big stream (20k viewers, chat
# flood) that blocked the event loop long enough to miss the websocket
# heartbeat → TikTok dropped the connection. Reconnect preserved the (now huge)
# file, so it disconnected again faster → death spiral.
#
# Fix: event handlers append to an in-memory list in O(1) (no disk in the hot
# path). A background daemon thread flushes all dirty buffers to disk every
# LOG_FLUSH_INTERVAL seconds (one batched write per file, off the event loop).
# The dashboard keeps reading the json files as before — just refreshed every
# ~2s instead of per-message. Post-stream reports are unaffected.
LOG_FLUSH_INTERVAL = 2.0
_log_buffers = {}            # log_file path -> list of entries
_log_dirty = set()           # log_file paths with unflushed changes
_log_buffer_lock = _threading.Lock()
_log_flusher_started = False
_stream_ended_cleanly = False   # set True only on LiveEndEvent (real stream end)


def _buffer_append(log_file, entry):
    """O(1) in-memory append. No disk I/O — the flush thread persists it."""
    with _log_buffer_lock:
        if log_file not in _log_buffers:
            _log_buffers[log_file] = []
        _log_buffers[log_file].append(entry)
        _log_dirty.add(log_file)


def _buffer_init(log_file, default=None):
    """Load existing on-disk entries into the buffer (used on reconnect so the
    flush thread doesn't overwrite preserved data with an empty array)."""
    default = [] if default is None else default
    with _log_buffer_lock:
        _log_buffers[log_file] = load_json(log_file, default)
        _log_dirty.discard(log_file)


def _buffer_clear(log_file, default=None):
    """Reset the buffer AND the on-disk file (used on a fresh session)."""
    default = [] if default is None else default
    with _log_buffer_lock:
        _log_buffers[log_file] = list(default)
        _log_dirty.discard(log_file)
    try:
        safe_json_write(list(default), log_file)
    except Exception:
        pass


def _flush_buffers_once():
    """Snapshot dirty buffers under lock (fast), write to disk outside the lock
    (slow I/O doesn't block event-loop appends)."""
    with _log_buffer_lock:
        dirty = list(_log_dirty)
        snapshot = {f: list(_log_buffers.get(f, [])) for f in dirty}
        _log_dirty.clear()
    for f, data in snapshot.items():
        try:
            safe_json_write(data, f)
        except Exception as e:
            print(f"[FLUSH] Error writing {os.path.basename(f)}: {e}", flush=True)


def _log_flush_worker():
    while True:
        time.sleep(LOG_FLUSH_INTERVAL)
        try:
            _flush_buffers_once()
        except Exception as e:
            print(f"[FLUSH] Worker error: {e}", flush=True)


def _start_log_flusher():
    """Start the flush daemon once. Safe to call multiple times."""
    global _log_flusher_started
    if _log_flusher_started:
        return
    _log_flusher_started = True
    t = _threading.Thread(target=_log_flush_worker, daemon=True, name="log-flusher")
    t.start()
    print(f"[FLUSH] Log flush thread started (every {LOG_FLUSH_INTERVAL}s).", flush=True)


# Active streaks tracking (key: group_id, value: streak info dict)
active_streaks = {}
_active_streaks_snapshot_version = 0
_active_streaks_persisted_version = -1


def snapshot_active_streaks():
    """Create an event-loop-owned snapshot for background persistence."""
    global _active_streaks_snapshot_version
    import time
    now = time.time()
    stale = [gid for gid, streak in active_streaks.items()
             if now - streak.get("last_updated", 0) > 30]
    for gid in stale:
        del active_streaks[gid]
    if stale:
        print(f"[STREAKS] Removed {len(stale)} stale streak(s)")
    _active_streaks_snapshot_version += 1
    return (
        {gid: dict(streak) for gid, streak in active_streaks.items()},
        _active_streaks_snapshot_version,
    )


def save_active_streaks(snapshot, version):
    """Persist one immutable snapshot without allowing stale worker overwrite."""
    global _active_streaks_persisted_version
    try:
        with _log_lock:
            if version <= _active_streaks_persisted_version:
                return
            safe_json_write(snapshot, paths.data("active_streaks.json"))
            _active_streaks_persisted_version = version
    except Exception as e:
        print(f"Error writing active streaks: {e}")

# ==========================================
# COIN GOAL JAR (native overlay state)
# ==========================================
# Persistent jar state for the pixelated glass jar overlay.
# Carries across streams/restarts — Khito resets manually.
# Gifts add their total_coin to `current`. Dashboard popup can set/adjust
# current, change goal, label, sublabel — all live (overlay polls the file).
COIN_GOAL_FILE = paths.data("coin_goal.json")
COIN_GOAL_DEFAULTS = {
    "current": 0,
    "goal": 10000,
    "label": "Tip Jar",
    "sublabel": "",
}

def load_coin_goal():
    """Read jar state, filling any missing keys with defaults."""
    data = load_json(COIN_GOAL_FILE, dict(COIN_GOAL_DEFAULTS))
    if not isinstance(data, dict):
        data = dict(COIN_GOAL_DEFAULTS)
    merged = dict(COIN_GOAL_DEFAULTS)
    merged.update({k: v for k, v in data.items() if k in COIN_GOAL_DEFAULTS})
    # Coerce numeric fields
    try:
        merged["current"] = max(0, int(merged["current"]))
    except (ValueError, TypeError):
        merged["current"] = 0
    try:
        merged["goal"] = max(1, int(merged["goal"]))
    except (ValueError, TypeError):
        merged["goal"] = 10000
    return merged

def add_coins_to_jar(amount):
    """Add `amount` coins to the jar (gift income). Locked read-add-write so
    manual edits from the dashboard are never clobbered."""
    try:
        amount = int(amount)
    except (ValueError, TypeError):
        return
    if amount <= 0:
        return
    try:
        with _log_lock:
            data = load_coin_goal()
            data["current"] = max(0, data["current"] + amount)
            safe_json_write(data, COIN_GOAL_FILE)
    except Exception as e:
        print(f"Error adding coins to jar: {e}")

# ==========================================
# GIFT GOAL (single-gift tracker overlay)
# ==========================================
GIFT_GOAL_FILE = paths.data("gift_goal.json")

def _cached_gift_asset_url(gift_id):
    """Return cached local gift animation URL if this gift was already downloaded."""
    try:
        from assets.gift_assets.manifest import get_entry
        entry = get_entry(int(gift_id))
        if entry and os.path.exists(entry.get("local", "")):
            return entry.get("local_url", "") or ""
    except Exception:
        pass
    return ""


def add_to_gift_goal(gift_id, repeat_count, asset_url=""):
    """Increment gift goal counter if this gift matches the configured goal gift."""
    try:
        gift_id_str = str(gift_id)
        with _log_lock:
            data = load_json(GIFT_GOAL_FILE, {})
            if not isinstance(data, dict):
                return
            configured_id = str(data.get("gift_id", ""))
            if not configured_id or configured_id != gift_id_str:
                return
            data["current"] = max(0, int(data.get("current", 0))) + int(repeat_count)
            if asset_url:
                data["gift_asset_url"] = asset_url
            elif not data.get("gift_asset_url"):
                cached_asset = _cached_gift_asset_url(gift_id_str)
                if cached_asset:
                    data["gift_asset_url"] = cached_asset
            safe_json_write(data, GIFT_GOAL_FILE)
    except Exception as e:
        print(f"Error updating gift goal: {e}")

# ==========================================
# TOP GIFTERS / TOP LIKERS LEADERBOARDS (rotating list overlay)
# ==========================================
# Per-stream leaderboards maintained in memory and flushed to JSON
# (throttled for bursty likes). Both reset on every fresh live via
# on_connect; consumed by /api/stats/topgifter. See stream_ranking.py.
import stream_ranking

GIFTER_RANKING_FILE = stream_ranking.GIFTER_RANKING_FILE
LIKER_RANKING_FILE = stream_ranking.LIKER_RANKING_FILE
AVATAR_CACHE_FILE = paths.data("avatar_cache.json")


def _image_url_from_model(image) -> str:
    """Best-effort first URL from TikTok ImageModel-like objects."""
    if not image:
        return ""
    for attr in ("url_list", "urls", "urlList"):
        try:
            urls = getattr(image, attr, None)
            if urls:
                return str(urls[0] or "")
        except Exception:
            pass
    for attr in ("url", "uri"):
        try:
            value = getattr(image, attr, "")
            if value:
                return str(value)
        except Exception:
            pass
    return ""


def _user_unique_id(user) -> str:
    """Stable TikTok username/ID when present; used as avatar-cache key."""
    if not user:
        return ""
    for attr in ("unique_id", "uniqueId", "sec_uid", "secUid", "user_id", "id"):
        try:
            value = getattr(user, attr, "")
            if value:
                return str(value).strip().lower()
        except Exception:
            pass
    return ""


def _user_permanent_id(user) -> str:
    """TikTok's PERMANENT numeric user id — never changes across renames.

    This is the correct long-term identity key for the points database.
    Falls back to unique_id (changeable @handle) only when the numeric id
    is missing, and to '' when nothing is available.
    """
    if not user:
        return ""
    for attr in ("id", "id_str"):
        try:
            value = getattr(user, attr, None)
            if value not in (None, "", 0):
                return str(value).strip()
        except Exception:
            pass
    for attr in ("unique_id", "uniqueId"):
        try:
            value = getattr(user, attr, "")
            if value:
                return str(value).strip().lower()
        except Exception:
            pass
    return ""


def _raw_avatar_url(user) -> str:
    """Extract current avatar URL from all known TikTokLive user image fields."""
    if not user:
        return ""
    for attr in (
        "avatar_thumb", "avatar_medium", "avatar_large",
        "avatarThumb", "avatarMedium", "avatarLarge",
        "profile_picture", "profilePicture", "display_avatar", "displayAvatar",
    ):
        try:
            url = _image_url_from_model(getattr(user, attr, None))
            if url:
                return url
        except Exception:
            pass
    return ""


def _avatar_cache_key(nick: str = "", unique_id: str = "") -> str:
    unique_id = (unique_id or "").strip().lower()
    if unique_id:
        return f"uid:{unique_id}"
    return f"nick:{(nick or '').strip().lower()}"


def _cache_avatar_url(nick: str, unique_id: str, avatar_url: str) -> str:
    """Persist a stable local avatar URL so expiring TikTok CDN URLs do not blank overlays."""
    if not avatar_url:
        return ""
    try:
        cache = load_json(AVATAR_CACHE_FILE, {})
        if not isinstance(cache, dict):
            cache = {}

        # Prefer a real local file cache. If download fails, keep the signed TikTok
        # URL as a temporary fallback so the image can still render while valid.
        local_url = avatar_url if is_local_avatar_url(avatar_url) else cache_avatar_image(avatar_url, nick, unique_id)
        stable_url = local_url or avatar_url
        now = int(time.time())
        keys = {_avatar_cache_key(nick, unique_id)}
        if nick:
            keys.add(_avatar_cache_key(nick, ""))

        # Short-circuit: likes fire in bursts and resolve_avatar_url() is called
        # on every like event. If every target key already holds this exact
        # stable URL, skip the disk rewrite entirely — otherwise a busy stream
        # hammers avatar_cache.json on every tap.
        already_cached = True
        for key in keys:
            existing = cache.get(key)
            if isinstance(existing, dict):
                if existing.get("avatar_url") != stable_url:
                    already_cached = False
                    break
            elif existing != stable_url:
                already_cached = False
                break
        if already_cached:
            return stable_url

        for key in keys:
            cache[key] = {
                "nick": nick or "",
                "unique_id": unique_id or "",
                "avatar_url": stable_url,
                "source_url": avatar_url if not is_local_avatar_url(avatar_url) else "",
                "updated_at": now,
            }
        safe_json_write(cache, AVATAR_CACHE_FILE)
        return stable_url
    except Exception as e:
        print(f"[!] Avatar cache write failed: {e}")
    return avatar_url


def _cached_avatar_url(nick: str = "", unique_id: str = "") -> str:
    try:
        cache = load_json(AVATAR_CACHE_FILE, {})
        if not isinstance(cache, dict):
            return ""
        for key in (_avatar_cache_key(nick, unique_id), _avatar_cache_key(nick, "")):
            entry = cache.get(key)
            if isinstance(entry, dict) and entry.get("avatar_url"):
                return str(entry.get("avatar_url") or "")
            if isinstance(entry, str) and entry:
                return entry
    except Exception:
        pass
    return ""


def resolve_avatar_url(user=None, nick: str = "", unique_id: str = "") -> str:
    """Current avatar URL, falling back to last-known URL when TikTokLive omits it."""
    uid = unique_id or _user_unique_id(user)
    avatar_url = _raw_avatar_url(user)
    if avatar_url:
        return _cache_avatar_url(nick, uid, avatar_url)
    return _cached_avatar_url(nick, uid)


def update_gifter_ranking(nick, avatar_url, total_coins, unique_id=""):
    """Accumulate coins per gifter for the current live (top 10 served).

    Thin wrapper over stream_ranking — the gifter board resets on every
    fresh live; see on_connect. Gifts are rare, so writes are immediate.
    """
    try:
        avatar_url = avatar_url or _cached_avatar_url(nick, unique_id)
        stream_ranking.update(
            GIFTER_RANKING_FILE, nick, avatar_url, total_coins,
            unique_id=unique_id, amount_key="total_coins",
            count_key="gift_count", force=True,
        )
    except Exception as e:
        print(f"Error updating gifter ranking: {e}")


def update_liker_ranking(nick, avatar_url, likes, unique_id=""):
    """Accumulate likes per viewer for the current live (top 10 served).

    LikeEvent fires in bursts (one event carries `count` taps), so the
    store throttles disk writes internally.
    """
    try:
        avatar_url = avatar_url or _cached_avatar_url(nick, unique_id)
        stream_ranking.update(
            LIKER_RANKING_FILE, nick, avatar_url, likes,
            unique_id=unique_id, amount_key="total_likes",
            count_key="like_count",
        )
    except Exception as e:
        print(f"Error updating liker ranking: {e}")


@client.on(GiftEvent)
async def on_gift(event: GiftEvent):
    try:
        u = event.user
        nick = mc_safe(getattr(u, 'nickname', getattr(u, 'nick_name', ''))) if u else "Someone"
        gift = event.gift
        if gift is None:
            print(f"[!] GiftEvent with no gift data, skipping")
            return

        gift_name = getattr(gift, 'name', 'unknown') or 'unknown'
        gift_name_lower = gift_name.lower()
        gift_id = str(getattr(gift, 'id', '0'))
        diamond_count = getattr(gift, 'diamond_count', 0) or 0
        repeat_count = getattr(event, 'repeat_count', 1) or 1
        total_coin = repeat_count * diamond_count
        gift_type = getattr(gift, 'type', 0) or 0

        group_id = getattr(event, "group_id", None) or getattr(gift, "group_id", None)
        repeat_end = getattr(event, 'repeat_end', 1)
        is_streaking = (gift_type == 1) and (not bool(repeat_end))

        # Optional: top-gift animation asset for 100+ coin gifts.
        # Do NOT block the GiftEvent on first-time downloads. Cached assets are attached
        # immediately; new assets are downloaded in a background thread and patched into
        # gift_log.json when ready so the overlay can swap icon -> animation live.
        asset_url = ""
        asset_src_urls = []
        asset_pending = False
        if _is_gift_downloader_enabled() and diamond_count >= 100:
            try:
                asset_src_urls = _gift_asset_source_urls(event)
                if asset_src_urls:
                    try:
                        from assets.gift_assets.manifest import get_entry
                        cached = get_entry(int(gift_id))
                        if cached and os.path.exists(cached.get("local", "")):
                            asset_url = cached.get("local_url", "") or ""
                        else:
                            asset_pending = True
                    except Exception:
                        asset_pending = True
                else:
                    print(f"[GIFT-ASSET] No animation URL on GiftEvent for {gift_name} (id={gift_id})")
            except Exception as dl_err:
                print(f"[!] Gift asset lookup error for {gift_name}: {dl_err}")

        uid = _user_unique_id(u)
        # Avatar caching can perform an 8-second network download for a new
        # viewer. Gameplay dispatch must never wait for that cosmetic work.
        avatar_url = ""

        # Track active streaks
        if gift_type == 1 and group_id is not None:
            if is_streaking:
                import time
                active_streaks[group_id] = {
                    "user": nick,
                    "avatar_url": "",
                    "gift_name": gift_name,
                    "gift_id": gift_id,
                    "gift_icon": get_gift_icon(gift_id),
                    "count": repeat_count,
                    "last_updated": time.time(),
                }
            else:
                # Streak ended — remove from active streaks
                active_streaks.pop(group_id, None)

        # Context for template substitution
        ctx = {
            "gift_name": gift_name,
            "repeat_count": str(repeat_count),
            "user": nick,
            "total_coin": str(total_coin),
            "mc": MC_USERNAME,
            "amount": str(repeat_count),
            "gift_id": gift_id,
            "asset_url": asset_url,
        }

        completed_gift = (gift_type != 1) or (not is_streaking)
        immediate_batches = []

        # ── Gift Roulette reservation (plan: .hermes/plans/roulette-randomizer.md) ──
        # Gift-level randomization: a successful reservation CONSUMES this gift's
        # specific bundle and schedules the winner's full bundle to execute at
        # land time. GlobalActions and all real-gift bookkeeping stay unchanged.
        # Rejected spins (busy/cooldown/invalid pool/duplicate final) fall back
        # to the normal gift-specific actions so the viewer keeps their reward.
        # No YAML/disk work here: ROULETTE_CONFIG is a hot-reloaded in-memory
        # snapshot, and the catalog index is built only when the trigger hits.
        roulette_reserved = False
        if (completed_gift and ROULETTE_CONFIG.get("enabled")
                and not _should_skip_action_execution()
                and str(gift_id) == str(ROULETTE_CONFIG.get("trigger_gift_id", ""))):
            try:
                catalog_rows = await asyncio.to_thread(
                    gift_catalog.load_catalog, paths.data("available_gifts.json")
                )
                prepared = gift_roulette.prepare_spin(
                    ROULETTE_CONFIG,
                    GIFT_ACTIONS,
                    ROULETTE_NAMES,
                    ROULETTE_DESCRIPTIONS,
                    gift_roulette.build_catalog_index(catalog_rows),
                    ctx,
                    source="live",
                    profile=_active_profile_name(),
                )
                accepted, rl_reason = ROULETTE_RUNTIME.try_reserve(
                    prepared, int(ROULETTE_CONFIG.get("cooldown_ms", 2000))
                )
                if accepted:
                    ROULETTE_RUNTIME.mark_reserved_started()
                    roulette_reserved = True
                    spin_task = asyncio.create_task(
                        ROULETTE_RUNTIME.run_reserved(
                            prepared,
                            lambda actions, context: execute_actions(
                                actions, context, send_minecraft_command
                            ),
                        )
                    )
                    spin_task.add_done_callback(_log_roulette_task_done)
                    print(f"[ROULETTE] Spin started ({prepared.spin_id}) — trigger: {nick} {gift_name}")
                else:
                    print(f"[ROULETTE] Trigger rejected ({rl_reason}) — normal gift actions for {nick}")
            except gift_roulette.RouletteValidationError as rl_err:
                print(f"[ROULETTE] Pool invalid, normal gift actions for {nick}: {rl_err}")
            except Exception as rl_err:
                print(f"[ROULETTE] Unexpected error, normal gift actions for {nick}: {rl_err}")

        # Send global reward only when NOT streaking or it's a non-streakable gift.
        # Combine global + gift-specific actions into one concurrent dispatch so
        # rapid alternating gifts never wait behind persistence or each other.
        if completed_gift:
            print(f"[+] Gift: {nick} gave {gift_name} (id={gift_id}) {repeat_count} times. Total Coin: {total_coin}")
            default_gift_cmds = [
                {"type": "minecraft", "command": "chatgift {gift_name_q} {repeat_count} {user_q} {total_coin} {mc}"},
                {"type": "minecraft", "command": "scoreboard players add Coins stats {total_coin}"}
            ]
            immediate_batches.append((
                GIFT_ACTIONS.get("GlobalActions", default_gift_cmds),
                dict(ctx),
            ))
        else:
            print(f"[~] Gift streak: {nick} sending {gift_name} ({repeat_count} so far, streaking...)")

        # Check if the gift exists in config (by ID first, then by name for backward compat)
        gift_key = gift_id if gift_id in GIFT_ACTIONS else gift_name_lower

        if gift_key in GIFT_ACTIONS:
            # Streak delta check: try ID first, then name
            streak_key = gift_id if gift_id in GIFTS_WITH_STREAK_DELTA else gift_name_lower

            if (streak_key in GIFTS_WITH_STREAK_DELTA and gift_type == 1):
                # Update tracker BEFORE awaited actions so overlapping GiftEvent
                # handlers cannot read the same stale previous count. Keep ended
                # streaks briefly so duplicate final events do not re-trigger the
                # full repeat_count.
                streak_tracker.cleanup()
                delta = streak_tracker.apply(group_id, repeat_count, is_streaking)

                if delta > 0:
                    gift_ctx = dict(ctx)
                    gift_ctx["amount"] = str(delta)
                    immediate_batches.append((GIFT_ACTIONS.get(gift_key, []), gift_ctx))

            elif completed_gift and not roulette_reserved:
                # Roulette consumed this trigger's specific bundle; the winner
                # bundle fires at land time from the background spin task.
                immediate_batches.append((GIFT_ACTIONS.get(gift_key, []), dict(ctx)))

        # This is the latency-critical boundary. Minecraft actions already
        # fire-and-forget their connector I/O; do not put avatar downloads,
        # SQLite, ranking JSON, or overlay JSON ahead of this call.
        await asyncio.gather(*(
            execute_actions(actions, action_ctx, send_minecraft_command)
            for actions, action_ctx in immediate_batches
        ))

        # Everything below is bookkeeping/cosmetic state. Keep it off the
        # TikTok asyncio loop where it can block websocket heartbeats or later
        # GiftEvent tasks during an A/B/A/B burst.
        avatar_url = await asyncio.to_thread(resolve_avatar_url, u, nick, uid)

        if gift_type == 1 and group_id is not None:
            current_streak = active_streaks.get(group_id)
            if current_streak is not None:
                current_streak["avatar_url"] = avatar_url
            streak_snapshot, streak_version = snapshot_active_streaks()
            await asyncio.to_thread(
                save_active_streaks, streak_snapshot, streak_version
            )

        # Only log completed gifts (not mid-streak updates).
        if completed_gift:
            # Teach the catalog this gift before anything reads its icon. For
            # creator/event-exclusive gifts (Super GG, KhitoFam) this event is
            # the ONLY place their icon and price ever appear. Off-loop because
            # it touches disk; awaited so append_gift_log below sees the icon.
            await asyncio.to_thread(
                learn_gift_from_event, gift, gift_id, gift_name, diamond_count
            )

            asset_key = append_gift_log(
                gift_id,
                gift_name,
                nick,
                repeat_count,
                total_coin,
                diamond_count,
                asset_url=asset_url,
                asset_pending=asset_pending,
            )
            if asset_pending and asset_src_urls and asset_key:
                start_gift_asset_download(asset_key, gift_id, asset_src_urls)

            if _should_skip_action_execution():
                print(f"[LOG-ONLY] Skipping gifter ranking update for {nick}")
                print(f"[LOG-ONLY] Skipping points DB write for {nick}'s {gift_name} ({total_coin} coins)")
            else:
                update_gifter_ranking(nick, avatar_url, total_coin, uid)
                try:
                    import points_store
                    await asyncio.to_thread(
                        points_store.record_gift,
                        user_id=_user_permanent_id(u),
                        username=uid,
                        nickname=nick,
                        avatar_url=avatar_url,
                        coins=total_coin,
                        gift_id=gift_id,
                        gift_name=gift_name,
                    )
                except Exception as points_err:
                    print(f"[!] Points DB record failed: {points_err}")

            await asyncio.gather(
                asyncio.to_thread(add_coins_to_jar, total_coin),
                asyncio.to_thread(add_to_gift_goal, gift_id, repeat_count, asset_url),
            )

    except Exception as e:
        print(f"[!] Error in on_gift handler: {e}")
        import traceback
        traceback.print_exc()


followers_set = set()

@client.on(FollowEvent)
async def on_follow(event: FollowEvent):
    try:
        u = event.user
        uid = getattr(u, 'unique_id', '') if u else ""
        if uid and uid not in followers_set:
            nick = mc_safe(getattr(u, 'nickname', getattr(u, 'nick_name', ''))) if u else "Someone"
            followers_set.add(uid)

            # Log follow to dashboard; reuse last-known avatar if TikTokLive omits it.
            avatar_url = resolve_avatar_url(u, nick, uid)
            append_follow_log(nick, uid, avatar_url)
            print(f"[+] Follow: {nick} (@{uid}) followed the stream!")

            ctx = {"user": nick, "mc": MC_USERNAME, "amount": "1"}
            await execute_actions(
                EVENTS.get("Follow", []),
                ctx, send_minecraft_command
            )
    except Exception as e:
        print(f"[!] Error in on_follow handler: {e}")
        import traceback
        traceback.print_exc()

# Dynamically track like goals (one tracker per Like_N key)
# like_interval_trackers[event_key] = next milestone to fire at
# like_highest_total = highest total ever reported (prevents dip bugs)
like_interval_trackers = {}
like_highest_total = 0

@client.on(LikeEvent)
async def on_like(event: LikeEvent):
    global like_highest_total

    # Bug fix: TikTokLive sometimes reports a lower total due to batching/races.
    # Always use the highest recorded total so it never goes backwards.
    raw_total = event.total
    if raw_total < like_highest_total:
        event.total = like_highest_total
    else:
        like_highest_total = raw_total

    # Top Likers leaderboard: accumulate this batch of likes per user.
    # LikeEvent.count is the batch size; user is who tapped.
    try:
        user = getattr(event, "user", None)
        if user is not None:
            nick = getattr(user, "nickname", "") or ""
            if nick:
                batch = max(1, int(getattr(event, "count", 0) or 0))
                # Resolve the avatar through the SAME path gifters use:
                # extract the current TikTok URL, seed the persistent
                # avatar cache, and fall back to the last-known URL when
                # TikTokLive omits the picture on a like event. This keeps
                # liker avatars from regressing to initials while a usable
                # avatar exists for the same user.
                uid = getattr(user, "unique_id", "") or ""
                avatar_url = resolve_avatar_url(user, nick, uid)
                stream_ranking.update(
                    LIKER_RANKING_FILE, nick, avatar_url,
                    batch, unique_id=uid,
                    amount_key="total_likes", count_key="like_batches",
                )
    except Exception:
        pass

    ctx = {"total_likes": str(event.total), "mc": MC_USERNAME, "user": "", "amount": "1"}

    # Process all Like events: "Like" and "Like_*" keys
    for event_key, like_config in EVENTS.items():
        if event_key != "Like" and not event_key.startswith("Like_"):
            continue

        if isinstance(like_config, dict):
            mode = like_config.get("mode", "every_like")
            interval = like_config.get("interval", 1000)
            actions = like_config.get("actions", [])

            if mode == "every_like":
                # Fire on every like
                default_like_cmds = [
                    {"type": "minecraft", "command": "scoreboard players set Likes stats {total_likes}"}
                ]
                await execute_actions(
                    actions if actions else default_like_cmds,
                    ctx, send_minecraft_command
                )
            elif mode == "every_n":
                # Fire when total_likes crosses the next interval milestone.
                # Simple: tracker stores the NEXT milestone to fire at.
                if event_key not in like_interval_trackers:
                    # Initialize: first milestone is the first multiple of interval
                    # above current total (or interval itself if at 0)
                    like_interval_trackers[event_key] = (math.floor(event.total / interval) + 1) * interval

                next_milestone = like_interval_trackers[event_key]
                if event.total >= next_milestone:
                    like_interval_trackers[event_key] = next_milestone + interval
                    if actions:
                        await execute_actions(actions, ctx, send_minecraft_command)
        else:
            # Legacy: like_config is a list of actions (treat as every_like)
            default_like_cmds = [
                {"type": "minecraft", "command": "scoreboard players set Likes stats {total_likes}"}
            ]
            actions = like_config if isinstance(like_config, list) else []
            await execute_actions(
                actions if actions else default_like_cmds,
                ctx, send_minecraft_command
            )


# Helpers for comments
async def log_and_send(tag: str, gifter_level, nick: str, comment: str):
    """Sends a chatlog to Minecraft. tag can be comma-separated for multi-badge (e.g. 'vip,superfan,member')."""
    # Build display-friendly tag for console
    display_tags = tag.replace(",", "][").upper()
    level_str = f"[{gifter_level}]" if gifter_level else ""
    log_text = f"[{display_tags}]{level_str} {nick} -> {comment}"
    try:
        print(log_text)
    except UnicodeEncodeError:
        print(log_text.encode('ascii', 'replace').decode('ascii'))

    ctx = {"tag": tag, "user": nick, "mc": MC_USERNAME, "comment": comment, "amount": "1"}
    default_comment_cmds = [
        {"type": "minecraft", "command": "chatlog {tag} {user_q} {mc} {comment}"}
    ]
    comment_actions = EVENTS.get("Comment", default_comment_cmds)
    await execute_actions(
        comment_actions,
        ctx, send_minecraft_command
    )


# ── Helper functions for on_comment() ──────────────────────────────

def _extract_user_info(event):
    """Extract user info from CommentEvent. Returns (user, nick, uid, user_info_dict)."""
    u = _ExtendedUser.from_user(event.user) if event.user else None
    nick = mc_safe(getattr(u, 'nickname', getattr(u, 'nick_name', ''))) if u else "Someone"
    comment = mc_safe(event.comment or "")
    uid = (getattr(u, 'unique_id', '')).lower() if u else ""

    # v7 ExtendedUser properties
    gifter_level = getattr(u, 'gifter_level', 0) if u else 0
    is_vip = uid in VIP_LIST
    is_superfan = event.user_is_super_fan
    member_level = getattr(u, 'member_level', 0) if u else 0
    is_member = bool(member_level)
    follow_status = getattr(getattr(u, 'follow_info', None), 'follow_status', 0) if u else 0
    is_friend = follow_status >= 2
    is_follower = follow_status == 1

    user_info = {
        "unique_id": uid,
        "gifter_level": gifter_level,
        "is_vip": is_vip,
        "is_superfan": is_superfan,
        "member_level": member_level,
        "is_member": is_member,
        "is_friend": is_friend,
        "is_follower": is_follower,
        "is_mod": getattr(u, 'is_moderator', False) if u else False,
    }

    return u, nick, uid, comment, user_info


def _build_tags(user_info):
    """Build tag hierarchy: VIP > SuperFan > Member > Friend > Follower > Newbie."""
    tags = []
    if user_info["is_vip"]:
        tags.append("vip")
    if user_info["is_superfan"]:
        tags.append("superfan")
    if user_info["is_member"]:
        tags.append("member")
    if user_info["is_friend"]:
        tags.append("friend")
    if user_info["is_follower"]:
        tags.append("follower")
    if not tags:
        tags = ["newbie"]

    # VIP shows ALL their badges, others show only highest
    if "vip" not in tags:
        tags = [tags[0]]

    return tags


def _check_chat_filter(tags, gifter_level, member_level):
    """Check if comment should be filtered. Returns True if filtered (should skip)."""
    if CHAT_FILTER and not (CHAT_FILTER & set(tags)):
        return True
    if CHAT_FILTER_MIN_GIFTER_LEVEL and gifter_level < CHAT_FILTER_MIN_GIFTER_LEVEL:
        return True
    if CHAT_FILTER_MIN_MEMBER_LEVEL and member_level < CHAT_FILTER_MIN_MEMBER_LEVEL:
        return True
    return False


async def _handle_tts_trigger(comment, nick, uid, user_info):
    """Handle TTS trigger if comment starts with TTS command."""
    try:
        tts_cfg_path = paths.data("tts_config.json")
        tts_cfg = load_json(tts_cfg_path, {})
        if not tts_cfg.get("enabled", True):
            return

        tts_cmd = tts_cfg.get("command", ".")
        comment_stripped = comment.strip()
        if not (tts_cmd and comment_stripped.startswith(tts_cmd)):
            return

        tts_text = comment_stripped[len(tts_cmd):].strip()
        if not tts_text:
            return

        # Parse effect tag (e.g. "*whisper* hello" → effect="whisper", text="hello")
        try:
            from tts_effects import parse_effect
            effect, tts_text = parse_effect(tts_text)
        except ImportError:
            effect = "normal"

        import urllib.request
        payload = json.dumps({
            "text": tts_text,
            "nick": nick,
            "user_info": user_info,
            "effect": effect
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{LOCAL_API_URL}/api/tts/speak",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=TTS_REQUEST_TIMEOUT)
    except Exception as tts_err:
        print(f"[TTS] Failed to send TTS request: {tts_err}")


@client.on(CommentEvent)
async def on_comment(event: CommentEvent):
    try:
        u, nick, uid, comment, user_info = _extract_user_info(event)

        # Build tag hierarchy: VIP > SuperFan > Member > Friend > Follower > Newbie
        tags = _build_tags(user_info)
        tag_str = ",".join(tags)

        # Chat filter: skip filtered users BEFORE any side effects
        if _check_chat_filter(tags, user_info["gifter_level"], user_info["member_level"]):
            return

        # Get avatar URL for chat display; also seeds the cache used by top-gifter podium.
        avatar_url = resolve_avatar_url(u, nick, uid)

        # Extract badge icons for chat display
        badges = _extract_badge_icons(u) if u else []

        append_chat_log(nick, uid, event.comment or "", tag_str, avatar_url, badges, user_info["gifter_level"], user_info["member_level"])
        await log_and_send(tag_str, user_info["gifter_level"], nick, comment)

        # ── TTS Trigger (configurable command) ──────────────────────────
        await _handle_tts_trigger(comment, nick, uid, user_info)

        # ── Spotify Song Request Commands ──────────────────────────────────
        try:
            song_cfg = sh.load_config()
            if song_cfg.get("enabled", True):
                play_cmd = song_cfg.get("play_command", "!play").lower()
                skip_cmd = song_cfg.get("skip_command", "!skip").lower()
                revoke_cmd = song_cfg.get("revoke_command", "!revoke").lower()

                comment_lower = comment.strip().lower()

                if comment_lower.startswith(play_cmd + " ") or comment_lower == play_cmd:
                    # Parse query: everything after the command
                    query = comment[len(play_cmd):].strip()
                    if not query:
                        return  # Just !play with no query

                    # Check permission (use user_info from _extract_user_info)
                    if not sh.check_permission("play", user_info, tags, user_info["gifter_level"], user_info["member_level"]):
                        sh.push_song_feedback(nick, "denied", "⊘", f"@{nick} — level too low to request songs")
                        return

                    # Search Spotify
                    results = sh.search_track(query, limit=5)
                    if isinstance(results, dict) and "error" in results:
                        print(f"[SONG] Search error: {results['error']}")
                        return
                    if not results:
                        sh.push_song_feedback(nick, "error", "✗", f'@{nick} — no results for "{query}"')
                        return

                    # Pick the first result
                    track = results[0]

                    # Add to queue
                    result = sh.add_to_queue(track, uid)
                    if "error" in result:
                        sh.push_song_feedback(nick, "error", "✗", f"@{nick} — {result['error']}")
                        return

                    print(f"[SONG] {nick} queued: {track['name']} by {track['artists']}")

                    # Try to push to Spotify if nothing is playing
                    token = sh.get_valid_token()
                    if token:
                        # Check LOCAL queue first — it's the source of truth and
                        # doesn't lag like Spotify's playback cache does. After
                        # !play A, the local queue correctly says A="playing" but
                        # Spotify's /me/player may still report the loop song for
                        # 2-5s. Using the local queue avoids that race.
                        local_queue = sh.load_queue()
                        has_local_playing = any(
                            q.get("status") == "playing" for q in local_queue
                        )

                        if has_local_playing:
                            # A user song is already playing in our local queue.
                            # Just queue this one locally — DON'T touch Spotify.
                            # The worker will push it to Spotify's queue, and
                            # Spotify will play it after the current song ends.
                            pass  # Status stays "queued" — no push needed
                        else:
                            # Check Spotify to decide: nothing playing (play it)
                            # vs loop song playing (replace context).
                            playback = sh.get_current_playback()
                            spotify_playing = playback.get("is_playing", False)
                            spotify_item = playback.get("item")

                            if not spotify_playing and not spotify_item:
                                # Nothing playing anywhere → play immediately via
                                # play_track_immediate (local-only architecture).
                                # DO NOT push to Spotify's queue — that would make
                                # !revoke impossible (Spotify has no remove-from-queue).
                                sh.play_track_immediate(track["uri"])
                                pos, entry = sh.get_next_to_play()
                                if pos is not None:
                                    sh.mark_as_playing(pos)
                                if entry:
                                    sh.add_to_history(dict(entry))
                            else:
                                # Loop song / non-user song is playing on Spotify,
                                # and no user song is in our local queue → replace
                                # context. The new track IS the new "now playing".
                                sh.play_track_immediate(track["uri"])
                                pos, entry = sh.get_next_to_play()
                                if pos is not None:
                                    sh.mark_as_playing(pos)
                                if entry:
                                    sh.add_to_history(dict(entry))

                    # Push feedback to overlay toast
                    pos = result.get("position", 0) + 1
                    sh.push_song_feedback(
                        nick, "success", "✓",
                        f"@{nick} queued {track['name']} \u2014 {track['artists']}",
                        f"Position #{pos} \u2022 Use !pull to remove your request"
                    )
                    return

                elif comment_lower == skip_cmd or comment_lower.startswith(skip_cmd):
                    # Check skip cooldown to prevent double-skips
                    global _last_skip_time
                    import time as _time
                    now = _time.time()
                    if now - _last_skip_time < SKIP_COOLDOWN:
                        sh.push_song_feedback(nick, "denied", "⊘", "Skip on cooldown, try again in a few seconds")
                        return

                    # Check permission for skip (use user_info from _extract_user_info)
                    if not sh.check_permission("skip", user_info, tags, user_info["gifter_level"], user_info["member_level"]):
                        sh.push_song_feedback(nick, "denied", "⊘", f"@{nick} — level too low to skip")
                        return

                    # Skip current track
                    _last_skip_time = now
                    result = sh.skip_track()
                    if isinstance(result, dict) and "error" in result:
                        print(f"[SONG] Skip error: {result['error']}")
                        return

                    # Immediately play the next song from local queue. Since we
                    # no longer push songs to Spotify's queue, skip_track() would
                    # skip the current track into silence — this prevents that.
                    played = sh.play_next_from_queue()
                    if played:
                        sh.push_song_feedback(nick, "success", "⏭", f"@{nick} skipped to next track")
                    else:
                        sh.push_song_feedback(nick, "success", "⏭", f"@{nick} skipped the track")
                    return

                elif comment_lower == revoke_cmd or comment_lower.startswith(revoke_cmd):
                    # Remove user's LATEST pending request (queued or pushed, but not yet playing).
                    # Songs stay in the local queue (not pushed to Spotify's queue) so revoke
                    # is always instant — just remove from local list. No Spotify API calls.
                    queue = sh.load_queue()
                    removed = False
                    pulled_track = ""
                    # Iterate in REVERSE to find the latest request
                    for i in range(len(queue) - 1, -1, -1):
                        q = queue[i]
                        if q.get("requested_by", "").lower() == uid and q.get("status") in ("queued", "pushed"):
                            pulled_track = f"{q.get('track_name', 'Unknown')} \u2014 {q.get('artist', 'Unknown')}"
                            sh.remove_from_queue(i, uid)
                            removed = True
                            print(f"[SONG] {nick} revoked: {q.get('track_name', '')} (status: {q.get('status')})")
                            break

                    if removed:
                        sh.push_song_feedback(
                            nick, "success", "↩",
                            f"@{nick} pulled {pulled_track}",
                            "Request removed from queue"
                        )
                    else:
                        sh.push_song_feedback(nick, "denied", "⊘", f"@{nick} — no pending request to pull")
                    return

        except ImportError:
            # spotify_handler not available, skip song commands
            pass
        except Exception as e:
            print(f"[SONG] Error handling song command: {e}")
            import traceback
            traceback.print_exc()

    except Exception as e:
        print(f"[!] Error in on_comment handler: {e}")
        import traceback
        traceback.print_exc()


@client.on(SubNotifyEvent)
async def on_subscribe(event: SubNotifyEvent):
    """Fires when someone subscribes (v7 SubNotifyEvent)."""
    u = event.user
    nick = mc_safe(getattr(u, 'nickname', getattr(u, 'nick_name', ''))) if u else "Someone"

    print(f"======SUBSCRIBE DETECTED======")
    print(f"  Sub by: {nick}")
    print(f"  subscribe_type: {getattr(event, 'subscribe_type', 'N/A')}")
    print(f"  subscribing_status: {getattr(event, 'subscribing_status', 'N/A')}")
    print(f"  old_subscribe_status: {getattr(event, 'old_subscribe_status', 'N/A')}")
    print(f"  sub_month: {getattr(event, 'sub_month', 'N/A')}")
    print(f"  is_send: {getattr(event, 'is_send', 'N/A')}")
    print(f"  is_custom: {getattr(event, 'is_custom', 'N/A')}")
    print(f"  gift_source: {getattr(event, 'gift_source', 'N/A')}")

    # Log for overlay
    append_superfan_log(nick, "subscribe")

    ctx = {"user": nick, "mc": MC_USERNAME, "amount": "1"}
    await execute_actions(
        EVENTS.get("SuperFan", []),
        ctx, send_minecraft_command
    )


# ---- SuperFan detection via raw BarrageEvent + custom event fallbacks ----
# Raw BarrageEvent is the reliable path Khito used before; custom SuperFanEvent wrappers are fallback only.
_superfan_dedupe = {}

def _superfan_seen_recently(nick: str, event_type: str, window: float = 8.0) -> bool:
    """Prevent duplicate SuperFan logs/rewards when raw BarrageEvent and custom wrapper both fire."""
    now = time.monotonic()
    key = (nick or "Someone", event_type)
    last = _superfan_dedupe.get(key, 0)
    _superfan_dedupe[key] = now
    # prune old keys cheaply
    for k, ts in list(_superfan_dedupe.items()):
        if now - ts > 30:
            _superfan_dedupe.pop(k, None)
    return now - last < window


def _event_nick(event) -> str:
    u = getattr(event, "user", None)
    return mc_safe(getattr(u, 'nickname', getattr(u, 'nick_name', ''))) if u else "Someone"


def _avatar_url(user) -> str:
    return resolve_avatar_url(user, "", _user_unique_id(user))


def _superfan_log_profile(event):
    """Best-effort profile fields for Recent SuperFans card."""
    raw_u = getattr(event, "user", None)
    try:
        u = _ExtendedUser.from_user(raw_u) if raw_u else None
    except Exception:
        u = raw_u
    uid = (getattr(u, 'unique_id', '') or '').lower() if u else ""
    info = {
        "is_vip": uid in VIP_LIST,
        "is_superfan": True,
        "is_member": bool(getattr(u, 'member_level', 0)) if u else False,
        "is_friend": (getattr(getattr(u, 'follow_info', None), 'follow_status', 0) >= 2) if u else False,
        "is_follower": (getattr(getattr(u, 'follow_info', None), 'follow_status', 0) == 1) if u else False,
    }
    tags = ",".join(_build_tags(info))
    return {
        "nick": _event_nick(event),
        "unique_id": uid,
        "avatar_url": _avatar_url(u),
        "tags": tags,
        "badges": _extract_badge_icons(u) if u else []
    }


def _enum_value(value):
    """Return enum/int value without exploding on betterproto enum wrappers."""
    try:
        return int(value)
    except Exception:
        return str(value) if value is not None else ""


def _image_url(image) -> str:
    """Best-effort first URL from TikTok ImageModel-like objects."""
    if not image:
        return ""
    for attr in ("url_list", "urls"):
        try:
            urls = getattr(image, attr, None)
            if urls:
                return urls[0]
        except Exception:
            pass
    try:
        uri = getattr(image, "uri", "")
        if uri:
            return uri
    except Exception:
        pass
    return ""


def _superfan_box_details(event) -> dict:
    """Extract sender + envelope data so SuperFanBox send/claim can be separated."""
    details = {"box_source_event": type(event).__name__}
    try:
        from TikTokLive.proto.proto_utils import common_display_type
        common_dt = common_display_type(event.common) if getattr(event, "common", None) else ""
    except Exception:
        common_dt = ""
    if common_dt:
        details["common_display_type"] = common_dt

    info = getattr(event, "envelope_info", None)
    if info:
        field_map = {
            "envelope_id": "envelope_id",
            "envelope_idc": "envelope_idc",
            "sender_name": "send_user_name",
            "sender_id": "send_user_id",
            "diamond_count": "diamond_count",
            "people_count": "people_count",
            "unpack_at": "unpack_at",
            "created_at": "create_at",
            "room_id": "room_id",
            "skin_id": "skin_id",
            "vote_count": "vote_count",
            "super_fan_count": "super_fan_count",
        }
        for out_key, attr in field_map.items():
            try:
                val = getattr(info, attr, None)
            except Exception:
                val = None
            if val not in (None, "", 0):
                details[out_key] = val
        try:
            details["business_type"] = _enum_value(getattr(info, "business_type", None))
        except Exception:
            pass
        try:
            details["follow_show_status"] = _enum_value(getattr(info, "follow_show_status", None))
        except Exception:
            pass
        avatar = _image_url(getattr(info, "send_user_avatar", None))
        if avatar:
            details["sender_avatar_url"] = avatar

    markers = [str(s).lower() for s in _collect_event_strings(event)[:80]]
    details["box_phase"] = _classify_superfan_box_phase(common_dt, markers)
    if markers:
        # Keep a compact marker sample for next live test; not the entire proto dump.
        details["marker_sample"] = [s for s in markers if "superfan" in s or "box" in s or "envelope" in s or "claim" in s or "open" in s][:12]
    return details


def _classify_superfan_box_phase(common_dt: str, markers: list[str]) -> str:
    text = " ".join([common_dt.lower()] + markers)
    if any(token in text for token in ("_sent", " sent", "send", "sender", "commentsection_sent")):
        return "sent"
    if any(token in text for token in ("claim", "claimed", "open", "opened", "unpack", "receive", "received")):
        return "claimed"
    return "unknown"


async def _trigger_new_superfan(nick: str, source: str, display_types=None, event=None):
    if _superfan_seen_recently(nick, "new_superfan"):
        print(f"[SUPERFAN DEDUPE] skipped duplicate new_superfan: {nick} source={source}")
        return
    print(f"======NEW SUPERFAN DETECTED======")
    print(f"SuperFan: {nick} source={source}")
    if display_types is not None:
        print(f"display_types={display_types}")
    profile = _superfan_log_profile(event) if event is not None else {"unique_id": "", "avatar_url": "", "tags": "superfan", "badges": []}
    append_superfan_log(nick, "new_superfan", profile.get("unique_id", ""), profile.get("avatar_url", ""), profile.get("tags", ""), profile.get("badges", []))
    ctx = {"user": nick, "mc": MC_USERNAME, "amount": "1"}
    await execute_actions(EVENTS.get("SuperFan", []), ctx, send_minecraft_command)


@client.on(BarrageEvent)
async def on_barrage_superfan(event: BarrageEvent):
    """Raw BarrageEvent SuperFan detector. Distinguishes join notice vs newly became SuperFan."""
    display_types = _superfan_display_types(event)
    strings = _collect_event_strings(event)
    superfan_strings = [s for s in strings if "superfan" in s or "super_fan" in s or "ttlive_superfan" in s]
    if not display_types and not superfan_strings:
        return
    print(f"[BARRAGE DEBUG] display_types={display_types} superfan_strings={superfan_strings[:8]}")
    _superfan_debug(f"BARRAGE_SUPERFAN display_types={display_types} superfan_strings={superfan_strings[:8]}")
    nick = _event_nick(event)

    markers = display_types + superfan_strings
    join_hit = any("ttlive_superfan_commentnotif_superfanjoined" in s for s in markers)
    upgrade_hit = any("super_fan_upgrade" in s or "superfan_upgrade" in s for s in markers)
    new_hit = any(
        "ttlive_superfan_commentnotif_someonebecamesuperfan" in s
        or "becoming_super_fan" in s
        or "becomingsuperfan" in s
        for s in markers
    )

    if join_hit:
        if not _superfan_seen_recently(nick, "superfan_join"):
            print(f"======SUPERFAN JOINED (NO REWARD)======")
            print(f"SuperFan Join: {nick} source=raw_barrage_recursive")
            profile = _superfan_log_profile(event)
            append_superfan_log(nick, "superfan_join", profile.get("unique_id", ""), profile.get("avatar_url", ""), profile.get("tags", ""), profile.get("badges", []))
        return

    if upgrade_hit:
        if not _superfan_seen_recently(nick, "superfan_upgrade"):
            print(f"======SUPERFAN UPGRADE (NO NEW-SUPERFAN REWARD)======")
            print(f"SuperFan Upgrade: {nick} source=raw_barrage_recursive")
            profile = _superfan_log_profile(event)
            append_superfan_log(nick, "superfan_upgrade", profile.get("unique_id", ""), profile.get("avatar_url", ""), profile.get("tags", ""), profile.get("badges", []))
        return

    if new_hit:
        await _trigger_new_superfan(nick, "raw_barrage_recursive", markers, event)


def _collect_event_strings(obj, depth: int = 0, out=None) -> list[str]:
    """Best-effort recursive string extraction from parsed TikTok proto objects."""
    if out is None:
        out = []
    if obj is None or depth > 5:
        return out
    if isinstance(obj, str):
        if obj:
            out.append(obj.lower())
        return out
    if isinstance(obj, bytes):
        try:
            s = obj.decode("utf-8", errors="ignore").lower()
            if s:
                out.append(s)
        except Exception:
            pass
        return out
    if isinstance(obj, (int, float, bool)):
        return out
    if isinstance(obj, dict):
        for v in obj.values():
            _collect_event_strings(v, depth + 1, out)
        return out
    if isinstance(obj, (list, tuple, set)):
        for v in obj:
            _collect_event_strings(v, depth + 1, out)
        return out
    # betterproto/proto objects usually expose useful fields via __dict__
    try:
        for v in vars(obj).values():
            _collect_event_strings(v, depth + 1, out)
    except Exception:
        pass
    for name in ("badges", "badge_list", "display_text", "key", "display_type", "default_pattern", "url_list", "str", "text", "combine", "image", "content", "common_barrage_content", "public_area_message_common", "event"):
        try:
            _collect_event_strings(getattr(obj, name, None), depth + 1, out)
        except Exception:
            pass
    return out


def _obj_contains_superfan(obj, depth: int = 0) -> bool:
    """Best-effort scan for superfan markers in TikTok user badges / unknown payloads."""
    return any(
        "superfan" in s or "super_fan" in s or "super fan" in s or "ttlive_superfan" in s
        for s in _collect_event_strings(obj, depth)
    )


@client.on(JoinEvent)
async def on_join_superfan_badge(event: JoinEvent):
    """Fallback: some rooms only expose existing SuperFan as a JoinEvent user badge."""
    if not _obj_contains_superfan(getattr(event, "user", None)):
        return
    nick = _event_nick(event)
    if _superfan_seen_recently(nick, "superfan_join"):
        return
    print(f"======SUPERFAN JOINED (BADGE FALLBACK / NO REWARD)======")
    print(f"SuperFan Join: {nick} source=join_badge")
    _superfan_debug(f"JOIN_BADGE nick={nick}")
    profile = _superfan_log_profile(event)
    append_superfan_log(nick, "superfan_join", profile.get("unique_id", ""), profile.get("avatar_url", ""), profile.get("tags", ""), profile.get("badges", []))


@client.on(UnknownEvent)
async def on_unknown_superfan_probe(event: UnknownEvent):
    """Probe unknown payloads; log if any superfan-like marker appears."""
    if not _obj_contains_superfan(event):
        return
    nick = _event_nick(event)
    print(f"[SUPERFAN UNKNOWN PROBE] nick={nick} type={event.get_type() if hasattr(event, 'get_type') else type(event)}")
    _superfan_debug(f"UNKNOWN_SUPERFAN_LIKE nick={nick} type={type(event)} repr={repr(event)[:500]}")
    if not _superfan_seen_recently(nick, "superfan_join"):
        profile = _superfan_log_profile(event)
        append_superfan_log(nick, "superfan_join", profile.get("unique_id", ""), profile.get("avatar_url", ""), profile.get("tags", ""), profile.get("badges", []))

async def _trigger_superfan_box(event, source: str):
    """SuperFan gift box handler. EnvelopeEvent has no .user on this TikTokLive build."""
    details = _superfan_box_details(event)
    phase = details.get("box_phase", "unknown")
    sender_name = mc_safe(details.get("sender_name", "")) if details.get("sender_name") else ""
    nick = sender_name or _event_nick(event)
    event_type = "superfan_box_sent" if phase == "sent" else "superfan_box_claimed" if phase == "claimed" else "superfan_box_unknown"

    dedupe_key = details.get("envelope_id") or nick
    if _superfan_seen_recently(str(dedupe_key), event_type):
        print(f"[SUPERFAN DEDUPE] skipped duplicate {event_type}: {nick} source={source} envelope_id={details.get('envelope_id', '')}")
        return

    print(f"======SUPERFAN GIFT BOX ({phase.upper()})======")
    print(
        f"SuperFan Box {phase}: sender={nick} source={source} "
        f"envelope_id={details.get('envelope_id', '')} "
        f"diamonds={details.get('diamond_count', '')} people={details.get('people_count', '')}"
    )
    _superfan_debug(f"SUPERFAN_BOX phase={phase} details={json.dumps(details, ensure_ascii=False, default=str)[:1200]}")

    profile = _superfan_log_profile(event)
    unique_id = profile.get("unique_id", "")
    avatar_url = profile.get("avatar_url", "")
    if details.get("sender_id"):
        unique_id = str(details.get("sender_id"))
    if details.get("sender_avatar_url"):
        avatar_url = str(details.get("sender_avatar_url"))

    append_superfan_log(
        nick,
        event_type,
        unique_id,
        avatar_url,
        profile.get("tags", ""),
        profile.get("badges", []),
        extra=details,
    )

    # Only the sender-side event should trigger configured SuperFanBox actions.
    # The later opened/claimed event is log/feed-only so the same box cannot fire twice.
    if phase != "sent":
        print(f"[SUPERFAN BOX] logged {phase} event only; no actions executed")
        return

    ctx = {"user": nick, "mc": MC_USERNAME, "amount": str(details.get("diamond_count", "1") or "1")}
    ctx.update({k: str(v) for k, v in details.items() if isinstance(v, (str, int, float, bool))})
    await execute_actions(
        EVENTS.get("SuperFanBoxEvent", []),
        ctx, send_minecraft_command
    )


@client.on(EnvelopeEvent)
async def on_envelope_debug(event: EnvelopeEvent):
    """Envelope detector: SuperFan box arrives as ttLive superFanBox / business_type 19."""
    from TikTokLive.proto.proto_utils import common_display_type
    common_dt = common_display_type(event.common) if event.common else ""
    biz_type = getattr(event.envelope_info, "business_type", None) if event.envelope_info else None
    if common_dt or biz_type:
        print(f"[ENVELOPE DEBUG] common_display_type={common_dt} | business_type={biz_type}")
    biz_s = str(biz_type)
    if (common_dt and "superfanbox" in common_dt.lower().replace("_", "")) or biz_type == 19 or "19" in biz_s:
        await _trigger_superfan_box(event, "raw_envelope")

# ---- SuperFan detection via custom events (v7) ----

def _superfan_debug(line: str):
    """Append lightweight SuperFan detector debug lines for field discovery.

    Gated on Settings.DebugMode (live-read). When debug is OFF this is a no-op,
    which is what keeps superfan_debug.log from growing unbounded — every TikTok
    WS event would otherwise write a line here.
    """
    if not _is_debug_mode_enabled():
        return
    try:
        with open(SUPERFAN_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat()} {line}\n")
    except Exception:
        pass


def _superfan_display_types(event) -> list[str]:
    """Return lowercased SuperFan-ish markers from barrage/common/display text fields."""
    vals = []
    for attr in ("content", "common_barrage_content", "common"):
        obj = getattr(event, attr, None)
        if not obj:
            continue
        for key in ("display_type", "display_type_url"):
            dt = getattr(obj, key, None)
            if isinstance(dt, str) and dt:
                vals.append(dt.lower())
        display_text = getattr(obj, "display_text", None)
        if display_text:
            for key in ("key", "display_type", "default_pattern"):
                dt = getattr(display_text, key, None)
                if isinstance(dt, str) and dt:
                    vals.append(dt.lower())
    # de-dupe, preserve order
    return list(dict.fromkeys(vals))


@client.on(WebsocketResponseEvent)
async def on_ws_superfan_probe(event: WebsocketResponseEvent):
    """Raw WS probe: log message methods so we can find where SuperFan join lives now."""
    if not _is_debug_mode_enabled():
        return  # Debug off — skip the whole probe (this fires on every WS batch)
    try:
        messages = getattr(event.raw, "messages", []) or []
        methods = []
        for msg in messages:
            method = getattr(msg, "method", "") or ""
            payload = getattr(msg, "payload", b"") or b""
            methods.append(f"{method}:{len(payload)}")

            # If method name hints at fan/member/barrage/envelope/social, log payload prefix too.
            m = method.lower()
            if any(token in m for token in ("barrage", "envelope", "member", "social", "notice", "toast", "fans", "fan", "sub")):
                _superfan_debug(f"WS_METHOD method={method} payload_len={len(payload)} payload_hex_prefix={payload[:80].hex()}")

        if methods:
            _superfan_debug("WS_BATCH methods=" + ",".join(methods[:80]))
    except Exception as e:
        _superfan_debug(f"WS_PROBE_ERROR {type(e).__name__}: {e}")


@client.on(SuperFanJoinEvent)
async def on_superfan_join(event: SuperFanJoinEvent):
    """Existing superfan joined the room. Log only; DO NOT trigger Minecraft reward."""
    nick = _event_nick(event)
    if _superfan_seen_recently(nick, "superfan_join"):
        return
    print(f"======SUPERFAN JOINED (NO REWARD)======")
    print(f"SuperFan Join: {nick} source=custom_event")
    print(f"display_types={_superfan_display_types(event)}")
    profile = _superfan_log_profile(event)
    append_superfan_log(nick, "superfan_join", profile.get("unique_id", ""), profile.get("avatar_url", ""), profile.get("tags", ""), profile.get("badges", []))


@client.on(SuperFanEvent)
async def on_superfan(event: SuperFanEvent):
    """Fallback wrapper. Raw BarrageEvent is primary; guard excludes existing-superfan joins."""
    display_types = _superfan_display_types(event)
    nick = _event_nick(event)
    if any("ttlive_superfan_commentnotif_superfanjoined" in dt for dt in display_types):
        print(f"[SUPERFAN GUARD] Ignored join-notice misrouted as SuperFanEvent: {nick} display_types={display_types}")
        if not _superfan_seen_recently(nick, "superfan_join"):
            profile = _superfan_log_profile(event)
            append_superfan_log(nick, "superfan_join_ignored", profile.get("unique_id", ""), profile.get("avatar_url", ""), profile.get("tags", ""), profile.get("badges", []))
        return

    if any("super_fan_upgrade" in dt or "superfan_upgrade" in dt for dt in display_types):
        print(f"[SUPERFAN GUARD] Ignored upgrade misrouted as SuperFanEvent: {nick} display_types={display_types}")
        if not _superfan_seen_recently(nick, "superfan_upgrade"):
            profile = _superfan_log_profile(event)
            append_superfan_log(nick, "superfan_upgrade", profile.get("unique_id", ""), profile.get("avatar_url", ""), profile.get("tags", ""), profile.get("badges", []))
        return

    if any("ttlive_superfan_commentnotif_someonebecamesuperfan" in dt or "becoming_super_fan" in dt or "becomingsuperfan" in dt for dt in display_types):
        await _trigger_new_superfan(nick, "custom_event", display_types, event)


@client.on(SuperFanBoxEvent)
async def on_superfan_box(event: SuperFanBoxEvent):
    """Fallback wrapper for SuperFan box; this event has no .user in current TikTokLive."""
    await _trigger_superfan_box(event, "custom_event")


# ---- End of TikTok event handlers ----


def run_bot():
    print("Starting Main TikTok -> Minecraft Sync...", flush=True)
    print(f"Loaded {len(GIFT_ACTIONS)} configured gifts.", flush=True)
    bot_status.write_status(paths, "starting")

    from reconnect_policy import (
        INITIAL_RECONNECT_DELAY,
        MAX_RECONNECT_RETRIES,
        format_reconnect_delay,
        next_reconnect_delay,
    )

    reconnect_delay = INITIAL_RECONNECT_DELAY
    retry_count = 0
    max_retries = MAX_RECONNECT_RETRIES

    while retry_count < max_retries:
        try:
            bot_status.write_status(paths, "connecting", attempt=retry_count + 1, max_attempts=max_retries)
            # TikTok's/Euler's bulk live-check endpoint can intermittently return
            # an empty body, which TikTokLive then tries to parse as JSON. Room ID
            # resolution and the signed WebSocket remain healthy, so bypass only
            # that unreliable preflight and connect to the resolved room directly.
            client.run(fetch_gift_info=True, fetch_live_check=False)
            # client.run() returned. This happens BOTH on a real stream end AND
            # on a mid-stream heartbeat drop (TikTokLive returns rather than
            # raising). Only stop if LiveEndEvent fired; otherwise reconnect.
            try:
                _flush_buffers_once()
            except Exception:
                pass
            if _stream_ended_cleanly:
                print("Stream ended by streamer. Bot shutting down.", flush=True)
                bot_status.write_status(paths, "stopped")
                break
            retry_count += 1
            print(
                f"Connection dropped (run returned, {retry_count}/{max_retries}). "
                f"Reconnecting in {format_reconnect_delay(reconnect_delay)}...",
                flush=True,
            )
            bot_status.write_status(
                paths,
                "reconnecting",
                attempt=retry_count,
                max_attempts=max_retries,
                error="Connection dropped",
            )
            time.sleep(reconnect_delay)
            import random as _rr
            reconnect_delay = next_reconnect_delay(reconnect_delay, _rr.uniform(0, 2))
        except Exception as e:
            retry_count += 1
            from reconnect_diagnostics import format_connection_failure

            # Connection failures must always be actionable in the operator
            # console. Debug Mode controls noisy event probes, not crash details.
            # format_exception omits frame locals, so API keys/config secrets are
            # not dumped while the exact TikTokLive call site remains visible.
            failure_report = format_connection_failure(
                e,
                attempt=retry_count,
                max_attempts=max_retries,
            )
            print(failure_report, flush=True)
            bot_status.write_status(
                paths,
                "failed",
                attempt=retry_count,
                max_attempts=max_retries,
                error=str(e),
            )
            print(f"Reconnecting in {format_reconnect_delay(reconnect_delay)}...", flush=True)
            time.sleep(reconnect_delay)
            # Exponential backoff with jitter
            import random as _rr
            reconnect_delay = next_reconnect_delay(reconnect_delay, _rr.uniform(0, 2))
        else:
            # Successful reconnect path resets backoff so the next drop starts fresh.
            if not _stream_ended_cleanly:
                reconnect_delay = INITIAL_RECONNECT_DELAY

    if retry_count >= max_retries:
        print("Max reconnection attempts reached. Bot shutting down permanently.", flush=True)
        bot_status.write_status(
            paths,
            "failed",
            attempt=retry_count,
            max_attempts=max_retries,
            error="Max reconnection attempts reached",
        )

if __name__ == '__main__':
    run_bot()
