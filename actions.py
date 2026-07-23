"""
actions.py — Action dispatcher for TikTokMCIntegrator

Supports action types:
  - minecraft: send RCON command
  - sound: play audio (local file or URL)
  - webhook: HTTP request
  - random: pick one action randomly from a list

Config format:
  - type: minecraft
    command: "give {mc} diamond {amount}"
  - type: sound
    file: "sounds/diamond.mp3"   # local file
    # OR
    url: "https://example.com/sound.mp3"  # internet
    volume: 0.8                  # optional (0.0-1.0)
  - type: webhook
    url: "https://example.com/hook"
    method: POST                 # optional, default POST
    body: {"key": "value"}       # optional
  - type: random
    actions:                     # list of actions to pick from
      - type: minecraft
        command: "give {mc} diamond 1"
      - type: minecraft
        command: "give {mc} emerald 1"

Backward compat:
  Old format (list of strings) auto-converts to minecraft actions.
"""

import asyncio
import json
import os
import random as _random
import tempfile
import threading

# ── Sound playback (lazy-loaded) ─────────────────────────────────────────────

_mixer = None
_mixer_lock = threading.Lock()
_mixer_initialized = False


def _ensure_mixer():
    """Initialize pygame mixer on first use. Thread-safe."""
    global _mixer, _mixer_initialized
    if _mixer_initialized:
        return _mixer is not None
    with _mixer_lock:
        if _mixer_initialized:
            return _mixer is not None
        try:
            import pygame
            pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=512)
            pygame.mixer.init()
            _mixer = pygame.mixer
            _mixer_initialized = True
            print("[SOUND] pygame mixer initialized")
            return True
        except ImportError:
            print("[SOUND] pygame not installed — sound actions disabled. Install: pip install pygame")
            _mixer_initialized = True
            return False
        except Exception as e:
            print(f"[SOUND] mixer init failed: {e}")
            _mixer_initialized = True
            return False


def _play_sound(file_path=None, url=None, volume=0.8):
    """Play a sound file (local or URL). Non-blocking."""
    if not _ensure_mixer():
        print("[SOUND] mixer unavailable, skipping")
        return

    try:
        if url:
            # Download to temp file, then play
            import urllib.request
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            tmp.close()
            urllib.request.urlretrieve(url, tmp.name)
            file_path = tmp.name

        if file_path and os.path.exists(file_path):
            ch = _mixer.Channel(7)  # dedicated channel for action sounds
            snd = _mixer.Sound(file_path)
            snd.set_volume(max(0.0, min(1.0, volume)))
            ch.play(snd)
        else:
            print(f"[SOUND] file not found: {file_path}")
    except Exception as e:
        print(f"[SOUND] playback error: {e}")


# ── Config migration ─────────────────────────────────────────────────────────

def migrate_actions(actions):
    """Convert old-format (list of strings) to new-format (list of dicts).

    Old: ["give {mc} diamond 1", "tntspawn {mc} 50 {user}"]
    New: [{"type": "minecraft", "command": "give {mc} diamond 1"}, ...]

    If already new format, returns as-is.
    """
    if not actions:
        return []

    migrated = []
    for action in actions:
        if isinstance(action, str):
            # Old format: plain string → minecraft action
            migrated.append({"type": "minecraft", "command": action})
        elif isinstance(action, dict):
            # Already new format
            migrated.append(action)
        else:
            # Unknown format, skip
            print(f"[ACTIONS] skipping unknown action format: {action}")
    return migrated


def migrate_config_actions(config):
    """Migrate all action lists in config from old format to new format.

    Handles: Gifts (including GlobalActions), Events (including Like dict)
    """
    # Gifts
    gifts = config.get("Gifts", {})
    if isinstance(gifts, dict):
        for gift_id, actions in gifts.items():
            if isinstance(actions, list):
                gifts[gift_id] = migrate_actions(actions)

    # Events
    events = config.get("Events", {})
    if isinstance(events, dict):
        for event_name, value in events.items():
            if isinstance(value, list):
                events[event_name] = migrate_actions(value)
            elif isinstance(value, dict) and "actions" in value:
                # Like event with {mode, interval, actions}
                value["actions"] = migrate_actions(value["actions"])

    return config


# ── Action execution ─────────────────────────────────────────────────────────

async def execute_actions(actions, context=None, send_mc_command=None):
    """Execute a list of actions in order.

    Args:
        actions: list of action dicts
        context: dict with template variables ({user}, {mc}, {amount}, etc.)
        send_mc_command: async function to send RCON command
    """
    if not actions:
        return

    ctx = context or {}

    async def run_action(action):
        if not isinstance(action, dict):
            return

        action_type = action.get("type", "minecraft")

        try:
            if action_type == "minecraft":
                await _execute_minecraft(action, ctx, send_mc_command)
            elif action_type == "sound":
                _execute_sound(action, ctx)
            elif action_type == "webhook":
                await _execute_webhook(action, ctx)
            elif action_type == "random":
                await _execute_random(action, ctx, send_mc_command)
            else:
                print(f"[ACTIONS] unknown action type: {action_type}")
        except Exception as e:
            print(f"[ACTIONS] error executing {action_type}: {e}")

    # Actions from one TikTok event are independent. Start them together so a
    # multi-command gift does not wait for a fresh RCON round-trip per command.
    await asyncio.gather(*(run_action(action) for action in actions))


async def _execute_minecraft(action, ctx, send_mc_command):
    """Execute a minecraft RCON command."""
    if not send_mc_command:
        return
    cmd = action.get("command", "")
    if not cmd:
        return

    # Math evaluation for {amount*N} patterns — do this BEFORE template substitution
    import re as _re
    def math_replacer(match):
        expr = match.group(1)  # e.g., "amount*50" or "amount*1500"
        try:
            # Split on operator: "amount*50" -> ["amount", "*", "50"]
            parts = _re.split(r'([+\-*/])', expr, maxsplit=1)
            if len(parts) == 3 and parts[0].strip() == "amount":
                amount_val = int(ctx.get("amount", 1))
                op = parts[1]
                num = int(parts[2].strip())
                if op == "*": return str(amount_val * num)
                elif op == "+": return str(amount_val + num)
                elif op == "-": return str(amount_val - num)
                elif op == "/": return str(amount_val // num) if num else str(amount_val)
            # Fallback: just return amount
            return str(ctx.get("amount", 1))
        except:
            return str(ctx.get("amount", 1))

    cmd = _re.sub(r'\{(amount[^}]*)\}', math_replacer, cmd)

    # Template substitution
    for key, val in ctx.items():
        cmd = cmd.replace(f"{{{key}}}", str(val))

    await send_mc_command(cmd)


def _execute_sound(action, ctx):
    """Play a sound file or URL."""
    file_path = action.get("file", "")
    url = action.get("url", "")
    volume = action.get("volume", 0.8)

    # Template substitution on file/url
    for key, val in ctx.items():
        file_path = file_path.replace(f"{{{key}}}", str(val))
        url = url.replace(f"{{{key}}}", str(val))

    # Run in thread to not block event loop
    threading.Thread(
        target=_play_sound,
        kwargs={"file_path": file_path or None, "url": url or None, "volume": volume},
        daemon=True
    ).start()


async def _execute_webhook(action, ctx):
    """Send an HTTP request to a webhook URL."""
    import urllib.request
    import urllib.parse

    url = action.get("url", "")
    if not url:
        return

    method = action.get("method", "POST").upper()
    headers = action.get("headers", {})
    body = action.get("body", None)

    # Template substitution
    for key, val in ctx.items():
        url = url.replace(f"{{{key}}}", str(val))
        if isinstance(body, str):
            body = body.replace(f"{{{key}}}", str(val))

    # Run in thread to not block event loop
    def _send():
        try:
            data = None
            if body:
                if isinstance(body, dict):
                    data = json.dumps(body).encode("utf-8")
                    headers.setdefault("Content-Type", "application/json")
                else:
                    data = str(body).encode("utf-8")

            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=10) as resp:
                print(f"[WEBHOOK] {method} {url} → {resp.status}")
        except Exception as e:
            print(f"[WEBHOOK] error: {e}")

    await asyncio.to_thread(_send)


async def _execute_random(action, ctx, send_mc_command):
    """Pick one action randomly from a list and execute it."""
    choices = action.get("actions", [])
    if not choices:
        return

    picked = _random.choice(choices)
    await execute_actions([picked], ctx, send_mc_command)


# ── Dynamic context builder ──────────────────────────────────────────────────

def build_context(event, template_vars, mc_username="", vip_list=None):
    """Extract template variables from any TikTokLive event object.

    Args:
        event: A TikTokLive event instance (any type).
        template_vars: List of variable names to extract (e.g., ["user", "mc", "amount"]).
        mc_username: The configured Minecraft username (fallback for {mc}).
        vip_list: Set of VIP usernames for mc mapping.

    Returns:
        dict: {var_name: value_string} for template substitution.
    """
    ctx = {}
    vip_list = vip_list or set()

    for var in template_vars:
        value = ""

        if var == "user":
            # Extract TikTok username from event.user
            u = getattr(event, "user", None)
            if u:
                # Try unique_id first, then nickname
                value = getattr(u, "unique_id", "") or ""
                if not value:
                    value = getattr(u, "nickname", "") or getattr(u, "nick_name", "") or ""

        elif var == "mc":
            # MC username from config, or try VIP list mapping
            value = mc_username or ""
            if not value:
                u = getattr(event, "user", None)
                if u:
                    uid = getattr(u, "unique_id", "") or ""
                    if uid in vip_list:
                        value = uid

        elif var == "comment":
            value = getattr(event, "comment", "") or ""

        elif var == "total_likes":
            value = str(getattr(event, "total", 0))

        elif var == "gift_name":
            gift = getattr(event, "gift", None)
            if gift:
                value = getattr(gift, "name", "") or "unknown"
            else:
                value = "unknown"

        elif var == "gift_id":
            gift = getattr(event, "gift", None)
            if gift:
                value = str(getattr(gift, "id", "0"))
            else:
                value = "0"

        elif var == "diamond_count":
            gift = getattr(event, "gift", None)
            if gift:
                value = str(getattr(gift, "diamond_count", 0) or 0)
            else:
                value = "0"

        elif var == "total_coin":
            gift = getattr(event, "gift", None)
            repeat = getattr(event, "repeat_count", 1) or 1
            if gift:
                diamond = getattr(gift, "diamond_count", 0) or 0
                value = str(repeat * diamond)
            else:
                value = "0"

        elif var == "repeat_count":
            value = str(getattr(event, "repeat_count", 1) or 1)

        elif var == "amount":
            # Generic amount — try repeat_count, then total, then 1
            rc = getattr(event, "repeat_count", None)
            if rc is not None:
                value = str(rc)
            else:
                total = getattr(event, "total", None)
                if total is not None:
                    value = str(total)
                else:
                    value = "1"

        elif var == "tag":
            value = getattr(event, "tag", "") or ""

        else:
            # Generic attribute extraction with fallbacks
            value = _safe_getattr(event, var)

        ctx[var] = str(value) if value is not None else ""

    return ctx


def _safe_getattr(event, var):
    """Safely extract a variable from an event, trying multiple paths."""
    # Direct attribute
    val = getattr(event, var, None)
    if val is not None:
        if isinstance(val, (str, int, float, bool)):
            return str(val)
        # For complex objects, try string conversion
        try:
            return str(val)
        except Exception:
            pass

    # Try event.data.var
    data = getattr(event, "data", None)
    if data:
        val = getattr(data, var, None)
        if val is not None:
            return str(val)

    # Try event.extra.var
    extra = getattr(event, "extra", None)
    if extra and isinstance(extra, dict):
        val = extra.get(var)
        if val is not None:
            return str(val)

    return ""


def migrate_custom_events_actions(config):
    """Migrate CustomEvents action lists from old format to new format."""
    custom = config.get("CustomEvents", {})
    if isinstance(custom, dict):
        for event_key, actions in custom.items():
            if isinstance(actions, list):
                custom[event_key] = migrate_actions(actions)
    return config


def migrate_to_events_redesign(config):
    """Migrate old config structure to the new Events redesign structure.

    Old structure:
      GlobalCommands.OnGift → Gifts.GlobalActions
      GlobalCommands.OnComment → Events.Comment
      GlobalCommands.OnLike → Events.Like (mode: every_like)
      Likes.Tier* → Events.Like (mode: every_n, interval from first tier goal)
      CustomEvents.* → Events.* (merge into Events)
      GlobalCommands, Likes, CustomEvents keys are removed.

    Returns migrated config dict.
    """
    events = config.get("Events", {})
    if not isinstance(events, dict):
        events = {}

    # ── Migrate GlobalCommands.OnComment → Events.Comment ──
    global_cmds = config.get("GlobalCommands", {})
    if isinstance(global_cmds, dict):
        on_comment = global_cmds.get("OnComment", [])
        if on_comment and "Comment" not in events:
            events["Comment"] = on_comment

        # ── Migrate GlobalCommands.OnGift → Gifts.GlobalActions ──
        on_gift = global_cmds.get("OnGift", [])
        gifts = config.get("Gifts", {})
        if not isinstance(gifts, dict):
            gifts = {}
        if on_gift and "GlobalActions" not in gifts:
            gifts["GlobalActions"] = on_gift
        config["Gifts"] = gifts

        # ── Migrate GlobalCommands.OnLike → Events.Like ──
        on_like = global_cmds.get("OnLike", [])
        if on_like and "Like" not in events:
            events["Like"] = {
                "mode": "every_like",
                "actions": on_like,
            }

    # ── Migrate Likes tiers → Events.Like_N ──
    likes = config.get("Likes", {})
    if isinstance(likes, dict) and likes:
        for tier_name, tier_data in likes.items():
            if isinstance(tier_data, dict):
                goal = tier_data.get("Goal", 10000)
                cmds = tier_data.get("Commands", [])
                like_key = f"Like_{goal}"
                if cmds and like_key not in events:
                    events[like_key] = {
                        "mode": "every_n",
                        "interval": goal,
                        "actions": cmds,
                    }

    # ── Migrate CustomEvents.* → Events.* ──
    custom_events = config.get("CustomEvents", {})
    if isinstance(custom_events, dict):
        for key, actions in custom_events.items():
            if key not in events and actions:
                events[key] = actions

    config["Events"] = events

    # ── Remove old keys ──
    for old_key in ("GlobalCommands", "Likes", "CustomEvents"):
        config.pop(old_key, None)

    return config
