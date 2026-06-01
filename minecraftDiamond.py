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
import yaml
import re
import os
from TikTokLive import TikTokLiveClient
from TikTokLive.client.web.web_settings import WebDefaults
from TikTokLive.events import ConnectEvent, CommentEvent, LikeEvent, GiftEvent, FollowEvent, SubNotifyEvent, DisconnectEvent, RoomUserSeqEvent, BarrageEvent, EnvelopeEvent
from TikTokLive.events.custom_events import SuperFanEvent, SuperFanBoxEvent
from mcrcon import MCRcon
from actions import migrate_config_actions, migrate_custom_events_actions, migrate_to_events_redesign, execute_actions, build_context
from event_registry import EVENT_REGISTRY, get_event_class
import spotify_handler as sh
from utils import load_json, save_json
from constants import *

# Monkey-patch TikTokLive v7.0.0a1 bug: _get_all_badge_info() was written for v2
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
# Resolve paths relative to the executable/script location (works both dev and packaged)
BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) \
           else os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.yml")
RELOAD_SIGNAL_FILE = ".reload_signal"

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
            if actions:
                await execute_actions(actions, ctx, send_minecraft_command)
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
    global VIP_LIST, GIFTS_WITH_STREAK_DELTA, GIFT_ACTIONS, EVENTS, GLOBAL_COMMANDS, CUSTOM_EVENTS, CHAT_FILTER, CHAT_FILTER_MIN_GIFTER_LEVEL, CHAT_FILTER_MIN_MEMBER_LEVEL
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
WebDefaults.tiktok_sign_api_key = EULER_API_KEY

# ==========================================
# RCON HELPER
# ==========================================
def __send_sync_command(command):
    try:
        with MCRcon(RCON_HOST, RCON_PASSWORD, port=RCON_PORT) as mcr:
            mcr.command(command)
    except Exception as e:
        print(f"Failed to send command '{command}': {e}")

async def send_minecraft_command(command):
    """
    Sends an RCON command without blocking the main event loop.
    """
    await asyncio.to_thread(__send_sync_command, command)


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
    """Lookup gift icon URL from available_gifts.json cache."""
    try:
        gifts = load_json("available_gifts.json", [])
        for g in gifts:
            if str(g.get("id")) == str(gift_id):
                return g.get("icon", "")
    except Exception:
        pass
    return ""

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

def append_gift_log(gift_id, gift_name, sender, repeat_count, total_coins, diamond_count=0):
    """Append a gift event to the rolling gift log for the dashboard."""
    try:
        log_file = "gift_log.json"
        with _log_lock:
            entries = load_json(log_file, [])
            entries.append({
                "gift_id": str(gift_id),
                "gift_name": gift_name,
                "icon": get_gift_icon(gift_id),
                "sender": sender,
                "repeat_count": repeat_count,
                "diamond_count": diamond_count,
                "total_coins": total_coins,
                "tier": get_gift_tier(total_coins),
                "timestamp": asyncio.get_event_loop().time()
            })
            safe_json_write(entries, log_file)
    except Exception as e:
        print(f"Error writing gift log: {e}")

def append_follow_log(nick, unique_id, avatar_url=""):
    """Append a follow event to the rolling follow log for the dashboard."""
    try:
        log_file = "follow_log.json"
        with _log_lock:
            entries = load_json(log_file, [])
            entries.append({
                "nick": nick,
                "unique_id": unique_id,
                "avatar_url": avatar_url,
                "timestamp": asyncio.get_event_loop().time()
            })
            safe_json_write(entries, log_file)
    except Exception as e:
        print(f"Error writing follow log: {e}")

def append_chat_log(nick, unique_id, comment, tags, avatar_url="", badges=None, gifter_level=0, member_level=0):
    """Log chat messages to chat_log.json for post-stream reports."""
    try:
        log_file = "chat_log.json"
        with _log_lock:
            entries = load_json(log_file, [])
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
            entries.append(entry)
            safe_json_write(entries, log_file)
    except Exception as e:
        print(f"Error writing chat log: {e}")

# ==========================================
def append_superfan_log(nick, event_type="new_superfan"):
    """Log superfan events to superfan_log.json for overlay."""
    try:
        log_file = "superfan_log.json"
        with _log_lock:
            entries = []
            if os.path.exists(log_file):
                try:
                    with open(log_file, "r", encoding="utf-8") as f:
                        entries = json.load(f)
                except (json.JSONDecodeError, IOError):
                    entries = []
            entries.append({
                "nick": nick,
                "event_type": event_type,
                "timestamp": time.monotonic()
            })
            safe_json_write(entries, log_file)
    except Exception as e:
        print(f"Error writing superfan log: {e}")

# EVENT HANDLERS (v7 — TikTokLive 7.0.0a1)
# ==========================================

@client.on(ConnectEvent)
async def on_connect(event: ConnectEvent):
    print(f"Connected to @{event.unique_id} (Room ID: {client.room_id})")
    
    # Check if this is a reconnect to the same stream
    is_reconnect = False
    try:
        prev_state = load_json("stream_state.json", {})
        if prev_state.get("room_id") == client.room_id:
            is_reconnect = True
            print(f"[RECONNECT] Same room — preserving stream data.")
    except Exception:
        pass
    
    if not is_reconnect:
        # Clear logs for fresh session
        for log_file in ["gift_log.json", "follow_log.json", "chat_log.json", "active_streaks.json", "superfan_log.json"]:
            try:
                save_json(log_file, [] if log_file != "active_streaks.json" else {})
            except Exception:
                pass

        # Clear in-memory active streaks
        active_streaks.clear()

        # Clear stale viewer stats from previous session
        save_json("viewer_stats.json", {"viewers": 0, "total_viewers": 0, "updated_at": asyncio.get_event_loop().time()})
    
    # Write stream state for report generation
    stream_state = {
        "room_id": client.room_id,
        "started_at": datetime.datetime.now().isoformat(),
        "username": event.unique_id
    }
    save_json("stream_state.json", stream_state)
    
    # Start config watcher for hot-reload (event loop is running now)
    asyncio.ensure_future(config_watcher())

    # Register any dynamic custom events from config
    register_dynamic_events()
    
    # Dump available gifts for the UI
    try:
        if hasattr(client, "gift_info") and isinstance(client.gift_info, dict) and "gifts" in client.gift_info:
            gifts_list = []
            
            for gift in client.gift_info["gifts"]:
                icon_url = ""
                # Try to extract the icon from the raw JSON dictionary structure
                if "icon" in gift and "url_list" in gift["icon"] and len(gift["icon"]["url_list"]) > 0:
                    icon_url = gift["icon"]["url_list"][0]
                elif "image" in gift and "url_list" in gift["image"] and len(gift["image"]["url_list"]) > 0:
                    icon_url = gift["image"]["url_list"][0]
                
                gifts_list.append({
                    "id": gift.get("id", 0),
                    "name": str(gift.get("name", "Unknown")).lower(),
                    "diamond_count": gift.get("diamond_count", 0),
                    "icon": icon_url
                })
            
            # Sort gifts by diamond count
            gifts_list.sort(key=lambda x: x["diamond_count"])
            
            with open("available_gifts.json", "w", encoding="utf-8") as f:
                json.dump(gifts_list, f, indent=2)
            print(f"Dumped {len(gifts_list)} available gifts to JSON for UI.")
    except Exception as e:
        print(f"Error dumping gifts to JSON: {e}")

@client.on(DisconnectEvent)
async def on_disconnect(event: DisconnectEvent):
    print(f"Disconnected. Room ID was: {client.room_id or 'N/A'}")
    # Zero out viewer stats so dashboard doesn't show stale data
    with open("viewer_stats.json", "w", encoding="utf-8") as f:
        json.dump({"viewers": 0, "total_viewers": 0, "updated_at": asyncio.get_event_loop().time()}, f)

@client.on(RoomUserSeqEvent)
async def on_room_user_seq(event: RoomUserSeqEvent):
    """Handle viewer count updates and write to JSON for the dashboard."""
    try:
        stats = {
            "viewers": getattr(event, 'total', 0),
            "total_viewers": getattr(event, 'total_user', 0),
            "updated_at": asyncio.get_event_loop().time()
        }
        with open("viewer_stats.json", "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
    except Exception as e:
        print(f"Error writing viewer stats: {e}")


# Tracking Delta Streaks
streak_tracker = {}

# File write lock — prevents race conditions on JSON logs
import threading as _threading
_log_lock = _threading.Lock()


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


# Active streaks tracking (key: group_id, value: streak info dict)
active_streaks = {}

def save_active_streaks():
    """Write active_streaks dict to JSON for the dashboard API."""
    try:
        with _log_lock:
            # Filter out stale streaks (no update in 30 seconds)
            import time
            now = time.time()
            stale = [gid for gid, s in active_streaks.items()
                     if now - s.get("last_updated", 0) > 30]
            for gid in stale:
                del active_streaks[gid]
            if stale:
                print(f"[STREAKS] Removed {len(stale)} stale streak(s)")
            safe_json_write(active_streaks, "active_streaks.json")
    except Exception as e:
        print(f"Error writing active streaks: {e}")

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

        # Extract user avatar URL
        avatar_url = ""
        try:
            thumb = getattr(u, 'avatar_thumb', None) if u else None
            if thumb and getattr(thumb, 'url_list', None):
                avatar_url = thumb.url_list[0]
        except Exception:
            pass

        # Track active streaks
        if gift_type == 1 and group_id is not None:
            if is_streaking:
                import time
                active_streaks[group_id] = {
                    "user": nick,
                    "avatar_url": avatar_url,
                    "gift_name": gift_name,
                    "gift_id": gift_id,
                    "gift_icon": get_gift_icon(gift_id),
                    "count": repeat_count,
                    "last_updated": time.time(),
                }
            else:
                # Streak ended — remove from active streaks
                active_streaks.pop(group_id, None)
            save_active_streaks()

        # Only log completed gifts (not mid-streak updates)
        if (gift_type != 1) or (not is_streaking):
            append_gift_log(gift_id, gift_name, nick, repeat_count, total_coin, diamond_count)

        # Context for template substitution
        ctx = {
            "gift_name": gift_name,
            "repeat_count": str(repeat_count),
            "user": nick,
            "total_coin": str(total_coin),
            "mc": MC_USERNAME,
            "amount": str(repeat_count),
            "gift_id": gift_id,
        }

        # Send global reward only when NOT streaking or it's a non-streakable gift
        if (gift_type != 1) or (not is_streaking):
            print(f"[+] Gift: {nick} gave {gift_name} (id={gift_id}) {repeat_count} times. Total Coin: {total_coin}")
            default_gift_cmds = [
                {"type": "minecraft", "command": "chatgift {gift_name} {repeat_count} {user} {total_coin} {mc}"},
                {"type": "minecraft", "command": "scoreboard players add Coins stats {total_coin}"}
            ]
            await execute_actions(
                GIFT_ACTIONS.get("GlobalActions", default_gift_cmds),
                ctx, send_minecraft_command
            )
        else:
            print(f"[~] Gift streak: {nick} sending {gift_name} ({repeat_count} so far, streaking...)")

        # Check if the gift exists in config (by ID first, then by name for backward compat)
        gift_key = gift_id if gift_id in GIFT_ACTIONS else gift_name_lower

        if gift_key in GIFT_ACTIONS:
            # Streak delta check: try ID first, then name
            streak_key = gift_id if gift_id in GIFTS_WITH_STREAK_DELTA else gift_name_lower

            if (streak_key in GIFTS_WITH_STREAK_DELTA and gift_type == 1):
                prev = streak_tracker.get(group_id, 0)
                delta = repeat_count - prev

                if delta > 0:
                    ctx["amount"] = str(delta)
                    await execute_actions(
                        GIFT_ACTIONS.get(gift_key, []),
                        ctx, send_minecraft_command
                    )

                streak_tracker[group_id] = repeat_count
                if not is_streaking:
                    streak_tracker.pop(group_id, None)

            elif (gift_type != 1) or (not is_streaking):
                await execute_actions(
                    GIFT_ACTIONS.get(gift_key, []),
                    ctx, send_minecraft_command
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

            # Log follow to dashboard
            avatar_url = ""
            try:
                thumb = getattr(u, 'avatar_thumb', None)
                if thumb and getattr(thumb, 'url_list', None):
                    avatar_url = thumb.url_list[0]
            except Exception:
                pass
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
        {"type": "minecraft", "command": "chatlog {tag} {user} {mc} {comment}"}
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
        tts_cfg_path = os.path.join(BASE_DIR, "tts_config.json")
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

        # Get avatar URL for chat display
        avatar_url = ""
        try:
            thumb = getattr(u, 'avatar_thumb', None) if u else None
            if thumb and getattr(thumb, 'url_list', None):
                avatar_url = thumb.url_list[0]
        except Exception:
            pass

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
                        # If nothing is playing, push immediately
                        playback = sh.get_current_playback()
                        if not playback.get("is_playing") and not playback.get("item"):
                            result_direct = sh.queue_track(track["uri"])
                            pos, entry = sh.get_next_to_play()
                            if pos is not None:
                                sh.mark_as_playing(pos)
                            # Add to history when direct-queued
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
                    
                    sh.push_song_feedback(nick, "success", "⏭", f"@{nick} skipped the track")
                    return

                elif comment_lower == revoke_cmd or comment_lower.startswith(revoke_cmd):
                    # Remove user's LATEST pending request (queued or pushed, but not yet playing)
                    queue = sh.load_queue()
                    removed = False
                    pulled_track = ""
                    # Iterate in REVERSE to find the latest request
                    for i in range(len(queue) - 1, -1, -1):
                        q = queue[i]
                        if q.get("requested_by", "").lower() == uid and q.get("status") in ("queued", "pushed"):
                            pulled_track = f"{q.get('track_name', 'Unknown')} \u2014 {q.get('artist', 'Unknown')}"
                            was_pushed = q.get("status") == "pushed"
                            sh.remove_from_queue(i, uid)
                            removed = True
                            print(f"[SONG] {nick} revoked: {q.get('track_name', '')} (status: {q.get('status')})")
                            # If it was already pushed to Spotify, skip it immediately
                            if was_pushed:
                                try:
                                    skip_result = sh.skip_track()
                                    print(f"[SONG] Auto-skip after pull: {skip_result}")
                                except Exception as skip_err:
                                    print(f"[SONG] Auto-skip failed (non-fatal): {skip_err}")
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


# ---- DEBUG: Log ALL barrage/envelope events to find superfan markers ----
# TODO: Remove after confirming SuperFanEvent detection works

@client.on(BarrageEvent)
async def on_barrage_debug(event: BarrageEvent):
    """DEBUG: Log every barrage event's display_type to catch superfan markers."""
    content_dt = getattr(event.content, "display_type", None) if event.content else None
    common_dt = getattr(event.common_barrage_content, "display_type", None) if event.common_barrage_content else None
    # Only log if there's a display_type worth seeing
    if content_dt or common_dt:
        print(f"[BARRAGE DEBUG] content.display_type={content_dt} | common_barrage.display_type={common_dt}")

@client.on(EnvelopeEvent)
async def on_envelope_debug(event: EnvelopeEvent):
    """DEBUG: Log every envelope event to catch superfan box markers."""
    from TikTokLive.proto.proto_utils import common_display_type
    common_dt = common_display_type(event.common) if event.common else ""
    biz_type = getattr(event.envelope_info, "business_type", None) if event.envelope_info else None
    if common_dt or biz_type:
        print(f"[ENVELOPE DEBUG] common_display_type={common_dt} | business_type={biz_type}")

# ---- SuperFan detection via custom events (v7) ----

@client.on(SuperFanEvent)
async def on_superfan(event: SuperFanEvent):
    """Fires when someone becomes a NEW superfan (not when existing superfan joins)."""
    u = event.user
    nick = mc_safe(getattr(u, 'nickname', getattr(u, 'nick_name', ''))) if u else "Someone"

    print(f"======NEW SUPERFAN DETECTED======")
    print(f"SuperFan: {nick}")

    # Log for overlay
    append_superfan_log(nick, "new_superfan")

    ctx = {"user": nick, "mc": MC_USERNAME, "amount": "1"}
    await execute_actions(
        EVENTS.get("SuperFan", []),
        ctx, send_minecraft_command
    )


@client.on(SuperFanBoxEvent)
async def on_superfan_box(event: SuperFanBoxEvent):
    """Fires when someone gifts a superfan box/bundle to the stream."""
    u = event.user
    nick = mc_safe(getattr(u, 'nickname', getattr(u, 'nick_name', ''))) if u else "Someone"

    print(f"======SUPERFAN GIFT BOX======")
    print(f"SuperFan Box from: {nick}")

    # Log for overlay
    append_superfan_log(nick, "superfan_box")

    ctx = {"user": nick, "mc": MC_USERNAME, "amount": "1"}
    await execute_actions(
        EVENTS.get("SuperFan", []),
        ctx, send_minecraft_command
    )


def run_bot():
    print("Starting Main TikTok -> Minecraft Sync...", flush=True)
    print(f"Loaded {len(GIFT_ACTIONS)} configured gifts.", flush=True)

    reconnect_delay = 5  # seconds before first retry
    max_delay = 300  # cap at 5 minutes
    retry_count = 0
    max_retries = 20  # after 20 failures, stop trying

    while retry_count < max_retries:
        try:
            client.run(fetch_gift_info=True)
            # Clean exit — stream ended naturally (no exception)
            print("Stream ended. Bot shutting down.", flush=True)
            break
        except Exception as e:
            retry_count += 1
            print(f"Disconnected unexpectedly ({retry_count}/{max_retries}): {e}", flush=True)
            print(f"Reconnecting in {reconnect_delay}s...", flush=True)
            time.sleep(reconnect_delay)
            # Exponential backoff with jitter
            import random as _rr
            reconnect_delay = min(reconnect_delay * 1.5 + _rr.uniform(0, 2), max_delay)

    if retry_count >= max_retries:
        print("Max reconnection attempts reached. Bot shutting down permanently.", flush=True)

if __name__ == '__main__':
    run_bot()
