import os
import sys
import shutil
import glob
import yaml
import subprocess
import threading
import json
import atexit
import time as _time
import asyncio as _asyncio
import datetime
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
from event_registry import get_registry_for_api, get_registry_with_categories, get_event_categories
from actions import migrate_to_events_redesign
import spotify_handler as sh
from utils import load_json, save_json, safe_json_read
from constants import *
from routes.spotify import spotify_bp
from routes.stats import stats_bp, init_stats_blueprint

# Resolve base directory — works both as .py script and as packaged .exe
BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) \
           else os.path.dirname(os.path.abspath(__file__))

# Flask: when frozen, templates/static are extracted to sys._MEIPASS
if getattr(sys, 'frozen', False):
    app = Flask(__name__,
                template_folder=os.path.join(sys._MEIPASS, 'templates'),
                static_folder=os.path.join(sys._MEIPASS, 'static'))
else:
    app = Flask(__name__)

# Register blueprints
app.register_blueprint(spotify_bp, url_prefix='/api/spotify')
app.register_blueprint(stats_bp, url_prefix='/api/stats')

# Initialize stats blueprint with BASE_DIR
init_stats_blueprint(BASE_DIR)

CONFIG_FILE = os.path.join(BASE_DIR, "config.yml")
PROFILES_DIR = os.path.join(BASE_DIR, "profiles")
ACTIVE_PROFILE_FILE = os.path.join(BASE_DIR, "active_profile.txt")

bot_process = None
bot_logs = []
_bot_logs_lock = threading.Lock()
MAX_LOGS = 0  # 0 = unlimited


@atexit.register
def _cleanup_bot():
    """Kill orphan bot subprocess on Flask crash/exit."""
    global bot_process
    if bot_process is not None and bot_process.poll() is None:
        try:
            bot_process.terminate()
            bot_process.wait(timeout=5)
            print("--- Bot terminated on exit ---")
        except Exception:
            bot_process.kill()


def get_active_profile():
    """Get the currently active profile name."""
    if os.path.exists(ACTIVE_PROFILE_FILE):
        with open(ACTIVE_PROFILE_FILE, "r") as f:
            return f.read().strip()
    return "default"


def set_active_profile(name):
    """Set the active profile name."""
    with open(ACTIVE_PROFILE_FILE, "w") as f:
        f.write(name)


def ensure_profiles_setup():
    """Ensure profiles directory exists with default profile."""
    if not os.path.exists(PROFILES_DIR):
        os.makedirs(PROFILES_DIR)
    
    active = get_active_profile()
    profile_path = os.path.join(PROFILES_DIR, f"{active}.yml")
    
    # If there's a config.yml but no profile, migrate it
    if os.path.exists(CONFIG_FILE) and not os.path.exists(profile_path):
        shutil.copy(CONFIG_FILE, profile_path)
    
    set_active_profile(active)


def load_config():
    """Load configuration from the active profile YAML file."""
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    # Auto-migrate old config structure
    config = migrate_to_events_redesign(config)
    return config


def save_config(data):
    """Save configuration to the active profile YAML file."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False, default_flow_style=False)
        
    # Keep the active profile in sync
    active = get_active_profile()
    profile_path = os.path.join(PROFILES_DIR, f"{active}.yml")
    with open(profile_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False, default_flow_style=False)

def signal_reload():
    """Signal the bot to hot-reload config changes."""
    signal_file = os.path.join(BASE_DIR, ".reload_signal")
    try:
        with open(signal_file, "w") as f:
            f.write("1")
        print("--- Config reload signaled to bot ---")
    except Exception as e:
        print(f"Failed to signal config reload: {e}")

def read_output(pipe):
    global bot_logs
    for line in iter(pipe.readline, ''):
        with _bot_logs_lock:
            bot_logs.append(line.strip())
            if MAX_LOGS > 0 and len(bot_logs) > MAX_LOGS:
                bot_logs.pop(0)

    # Bot process exited on its own (stream ended naturally)
    # Generate report and clean up
    global bot_process
    if bot_process is not None:
        try:
            bot_process.wait(timeout=5)
        except Exception:
            pass
        bot_process = None
        bot_logs.append("--- Stream Ended ---")
        try:
            generate_report()
            print("Auto-report saved (stream ended)")
        except Exception as e:
            print(f"Auto-report failed: {e}")
        # Zero out viewer stats
        stats_file = os.path.join(BASE_DIR, "viewer_stats.json")
        try:
            with open(stats_file, "w", encoding="utf-8") as f:
                json.dump({"viewers": 0, "total_viewers": 0}, f)
        except Exception:
            pass

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify(load_config())

@app.route("/api/config", methods=["POST"])
def update_config():
    data = request.json
    save_config(data)
    # Signal hot-reload if bot is running
    if bot_process is not None and bot_process.poll() is None:
        signal_reload()
    return jsonify({"status": "success", "message": "Configuration saved!"})

@app.route("/api/event-registry", methods=["GET"])
def get_event_registry():
    """Return the full event registry for the Event Browser UI."""
    return jsonify({
        "registry": get_registry_for_api(),
        "categories": get_event_categories(),
        "grouped": get_registry_with_categories(),
    })

@app.route("/api/profiles", methods=["GET"])
def get_profiles():
    if not os.path.exists(PROFILES_DIR):
        os.makedirs(PROFILES_DIR)
    files = glob.glob(os.path.join(PROFILES_DIR, "*.yml"))
    profiles = [os.path.basename(f)[:-4] for f in files]
    return jsonify({"profiles": profiles, "active": get_active_profile()})

@app.route("/api/profiles/switch", methods=["POST"])
def switch_profile():
    name = request.json.get("profile")
    profile_path = os.path.join(PROFILES_DIR, f"{name}.yml")
    if os.path.exists(profile_path):
        shutil.copy(profile_path, CONFIG_FILE)
        set_active_profile(name)
        # Signal hot-reload if bot is running
        if bot_process is not None and bot_process.poll() is None:
            signal_reload()
        return jsonify({"status": "success", "message": f"Switched to profile: {name}"})
    return jsonify({"status": "error", "message": "Profile not found"}), 404

@app.route("/api/profiles/create", methods=["POST"])
def create_profile():
    name = request.json.get("profile")
    duplicate = request.json.get("duplicate", False)
    
    if not name:
        return jsonify({"status": "error", "message": "Profile name required"}), 400
        
    profile_path = os.path.join(PROFILES_DIR, f"{name}.yml")
    if os.path.exists(profile_path):
        return jsonify({"status": "error", "message": "Profile already exists"}), 400
        
    if duplicate and os.path.exists(CONFIG_FILE):
        shutil.copy(CONFIG_FILE, profile_path)
    else:
        with open(profile_path, "w", encoding="utf-8") as f:
            yaml.dump({"Settings": {}}, f)
            
    shutil.copy(profile_path, CONFIG_FILE)
    set_active_profile(name)
    return jsonify({"status": "success", "message": f"Created profile: {name}"})

@app.route("/api/profiles/<name>", methods=["DELETE"])
def delete_profile(name):
    if name == get_active_profile():
        return jsonify({"status": "error", "message": "Cannot delete active profile"}), 400
        
    profile_path = os.path.join(PROFILES_DIR, f"{name}.yml")
    if os.path.exists(profile_path):
        os.remove(profile_path)
        return jsonify({"status": "success", "message": "Profile deleted"})
    return jsonify({"status": "error", "message": "Profile not found"}), 404

@app.route("/api/profiles/<name>/export", methods=["GET"])
def export_profile(name):
    profile_path = os.path.join(PROFILES_DIR, f"{name}.yml")
    if os.path.exists(profile_path):
        return send_file(profile_path, as_attachment=True, download_name=f"{name}.yml")
    return jsonify({"status": "error", "message": "Profile not found"}), 404

@app.route("/api/profiles/import", methods=["POST"])
def import_profile():
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file part"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No selected file"}), 400
        
    if file and file.filename.endswith('.yml'):
        name = os.path.splitext(file.filename)[0]
        name = secure_filename(name)
        if not name:
            name = "imported_profile"
            
        profile_path = os.path.join(PROFILES_DIR, f"{name}.yml")
        counter = 1
        original_name = name
        while os.path.exists(profile_path):
            name = f"{original_name}_{counter}"
            profile_path = os.path.join(PROFILES_DIR, f"{name}.yml")
            counter += 1
            
        file.save(profile_path)
        return jsonify({"status": "success", "message": f"Profile imported as '{name}'"})
        
    return jsonify({"status": "error", "message": "Only .yml files are allowed"}), 400

@app.route('/api/gifts/available', methods=['GET'])
def get_available_gifts():
    gifts_file = os.path.join(BASE_DIR, "available_gifts.json")
    if os.path.exists(gifts_file):
        try:
            with open(gifts_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data:
                    return jsonify(data)
        except Exception as e:
            pass
    
    # Fallback: fetch directly from TikTok API
    try:
        import requests as req
        resp = req.get("https://webcast.tiktok.com/webcast/gift/list/", params={"device_platform": "web"}, timeout=10)
        raw = resp.json().get("data", {})
        gifts = []
        for g in raw.get("gifts", []):
            icon_url = ""
            if g.get("icon") and g["icon"].get("url_list") and len(g["icon"]["url_list"]) > 0:
                icon_url = g["icon"]["url_list"][0]
            gifts.append({
                "id": g.get("id", 0),
                "name": str(g.get("name", "")).lower(),
                "diamond_count": g.get("diamond_count", 0),
                "icon": icon_url
            })
        gifts.sort(key=lambda x: x["diamond_count"])
        # Cache it for next time
        with open(gifts_file, "w", encoding="utf-8") as f:
            json.dump(gifts, f, indent=2)
        return jsonify(gifts)
    except Exception as e:
        return jsonify({"error": f"Could not fetch gifts: {str(e)}"}), 500

@app.route("/api/bot/start", methods=["POST"])
def start_bot():
    global bot_process, bot_logs
    if bot_process is None or bot_process.poll() is not None:
        try:
            bot_logs.clear()
            
            # Force UTF-8 encoding for Python subprocess to prevent emoji crashes
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUNBUFFERED"] = "1"  # Fix output buffering for the packaged exe
            
            # Hide the terminal window on Windows
            creationflags = 0
            if os.name == 'nt':
                creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
            
            # Determine bot executable path (dev vs packaged)
            if getattr(sys, 'frozen', False):
                bot_cmd = [sys.executable, '--run-bot']
            else:
                bot_cmd = [sys.executable, '-u', 'main.py', '--run-bot']

            bot_process = subprocess.Popen(
                bot_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace", # Replace unprintable unicode with ?
                bufsize=1,
                env=env,
                creationflags=creationflags
            )
            
            # Start a thread to read output so the buffer doesn't fill up and freeze the bot
            t = threading.Thread(target=read_output, args=(bot_process.stdout,))
            t.daemon = True
            t.start()
            
            return jsonify({"status": "success", "message": "Bot started!"})
        except Exception as e:
            return jsonify({"status": "error", "message": f"{str(e)} (Command: {bot_cmd})"}), 500
    return jsonify({"status": "warning", "message": "Bot is already running!"})

def generate_report():
    """Generate a post-stream report from all log files."""
    from report_helpers import (
        load_stream_state, calculate_stats,
        format_report_header, format_report_summary,
        format_report_top_gifters, format_report_gift_breakdown,
        format_report_followers, format_report_chat_history,
    )

    # Load data
    state = load_stream_state()
    gifts = load_json("gift_log.json")
    follows = load_json("follow_log.json")
    chat = load_json("chat_log.json")

    # Calculate stats
    now = datetime.datetime.now()
    stats = calculate_stats(gifts, follows, chat)

    # Build report
    lines = []
    lines.extend(format_report_header(state, now))
    lines.extend(format_report_summary(stats, gifts, follows, chat))
    lines.extend(format_report_top_gifters(stats["top_gifters"]))
    lines.extend(format_report_gift_breakdown(stats["gift_counts"]))
    lines.extend(format_report_followers(follows))
    lines.extend(format_report_chat_history(chat))

    lines.append("=" * 50)
    lines.append(f"  Report generated: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 50)

    report_text = "\n".join(lines)

    # Save report
    reports_dir = os.path.join(BASE_DIR, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    room_id = state.get("room_id", "unknown")
    filename = f"stream_{now.strftime('%Y-%m-%d_%H%M')}_{room_id}.txt"
    report_path = os.path.join(reports_dir, filename)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"--- Report saved: {filename} ---")
    return report_path

@app.route("/api/report/generate", methods=["POST"])
def generate_report_manual():
    """Manually trigger a post-stream report."""
    try:
        path = generate_report()
        return jsonify({"status": "success", "message": f"Report saved!", "path": path})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/bot/stop", methods=["POST"])
def stop_bot():
    global bot_process
    if bot_process is not None and bot_process.poll() is None:
        bot_process.terminate()
        bot_process.wait()
        bot_process = None
        # Generate post-stream report
        try:
            generate_report()
        except Exception as e:
            print(f"Report generation failed: {e}")
        bot_logs.append("--- Bot Terminated ---")
        # Zero out viewer stats so dashboard doesn't show stale data
        stats_file = os.path.join(BASE_DIR, "viewer_stats.json")
        try:
            with open(stats_file, "w", encoding="utf-8") as f:
                json.dump({"viewers": 0, "total_viewers": 0}, f)
        except Exception:
            pass
        return jsonify({"status": "success", "message": "Bot stopped!"})
    return jsonify({"status": "warning", "message": "Bot is not running!"})

@app.route("/api/bot/status", methods=["GET"])
def bot_status():
    global bot_process
    is_running = bot_process is not None and bot_process.poll() is None
    return jsonify({"running": is_running})

@app.route("/api/bot/logs", methods=["GET"])
def bot_logs_endpoint():
    """Return bot console logs."""
    with _bot_logs_lock:
        return jsonify({"logs": list(bot_logs)})

def get_active_streaks():
    data = safe_json_read(os.path.join(BASE_DIR, "active_streaks.json"))
    return jsonify(data if data is not None else {})

@app.route("/api/upload-sound", methods=["POST"])
def upload_sound():
    """Upload a sound file, save to sounds/ dir, return path."""
    if 'file' not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    # Save to sounds/ directory
    sounds_dir = os.path.join(BASE_DIR, "sounds")
    os.makedirs(sounds_dir, exist_ok=True)

    filename = secure_filename(file.filename)
    filepath = os.path.join(sounds_dir, filename)
    file.save(filepath)

    return jsonify({"path": filepath, "filename": filename})

@app.route("/api/preview-sound", methods=["GET"])
def preview_sound():
    """Serve a sound file for preview playback."""
    filepath = request.args.get("path", "")
    if not filepath or not os.path.isfile(filepath):
        return jsonify({"error": "File not found"}), 404

    # Security: only allow serving from the sounds/ directory
    sounds_dir = os.path.join(BASE_DIR, "sounds")
    real_path = os.path.realpath(filepath)
    real_sounds = os.path.realpath(sounds_dir)
    if not real_path.startswith(real_sounds):
        return jsonify({"error": "Access denied"}), 403

    return send_file(filepath, mimetype="audio/mpeg")

@app.route("/overlay-demo/<overlay_type>")
def overlay_demo_page(overlay_type):
    """Demo overlay with dark background for preview."""
    valid_types = ['chat', 'gifts', 'follows', 'superfan', 'topgift', 'topstreak', 'song']
    if overlay_type not in valid_types:
        return "Invalid overlay type", 404
    return render_template("overlay_demo.html", overlay_type=overlay_type)


@app.route("/overlay/<overlay_type>")
def overlay_page(overlay_type):
    """Serve overlay pages for OBS browser sources."""
    valid_types = ['chat', 'gifts', 'follows', 'superfan', 'topgift', 'topstreak', 'song']
    if overlay_type not in valid_types:
        return "Invalid overlay type", 404
    return render_template("overlay.html", overlay_type=overlay_type)


# ── TTS (edge-tts) ──────────────────────────────────────────────────
_tts_last_at = 0
_tts_user_at = {}  # {uid: last_timestamp}

# Shared asyncio event loop for TTS (avoids asyncio.run() in Flask threads)
_tts_loop = _asyncio.new_event_loop()
_tts_loop_thread = threading.Thread(target=_tts_loop.run_forever, daemon=True)
_tts_loop_thread.start()


def _run_async(coro):
    """Run a coroutine in the shared TTS event loop."""
    import concurrent.futures
    future = _asyncio.run_coroutine_threadsafe(coro, _tts_loop)
    return future.result(timeout=30)


TTS_CONFIG_FILE = os.path.join(BASE_DIR, "tts_config.json")
TTS_HISTORY_FILE = os.path.join(BASE_DIR, "tts_history.json")

def _load_tts_history():
    """Load TTS history from JSON file."""
    data = load_json(TTS_HISTORY_FILE, [])
    return data if isinstance(data, list) else []

def _save_tts_history(history):
    """Save TTS history to JSON file (keep last MAX_TTS_HISTORY entries)."""
    history = history[-MAX_TTS_HISTORY:]
    save_json(TTS_HISTORY_FILE, history)

def _load_tts_config():
    """Load TTS config with defaults."""
    defaults = {
        "enabled": True,
        "command": ".",
        "voice": "en-US-AriaNeural",
        "speed": "+0%",
        "pitch": "+0Hz",
        "max_length": MAX_TTS_TEXT_LENGTH,
        "global_cooldown": DEFAULT_GLOBAL_COOLDOWN,
        "per_user_cooldown": DEFAULT_USER_COOLDOWN,
        "member_min_level": 0,
        "permission": {
            "everyone": True,
            "followers": False,
            "friends": False,
            "superfans": False,
            "members": False,
            "vip": False,
            "mods": False,
            "whitelist": []
        }
    }
    saved = load_json(TTS_CONFIG_FILE, {})
    # Merge with defaults for backward compat
    for k, v in defaults.items():
        saved.setdefault(k, v)
    return saved

def _save_tts_config(cfg):
    """Save TTS config."""
    save_json(TTS_CONFIG_FILE, cfg)

def _check_tts_permission(cfg, user_info):
    """Check if a user has TTS permission. Returns (allowed, reason)."""
    perm = cfg.get("permission", {})
    uid = (user_info.get("unique_id") or "").lower()

    # Whitelist always wins
    if uid and uid in [w.lower() for w in perm.get("whitelist", [])]:
        return True, "whitelisted"

    if perm.get("everyone"):
        return True, "everyone"
    if perm.get("vip") and user_info.get("is_vip"):
        return True, "vip"
    if perm.get("superfans") and user_info.get("is_superfan"):
        return True, "superfan"
    if perm.get("members") and user_info.get("is_member"):
        min_lvl = cfg.get("member_min_level", 0)
        member_lvl = user_info.get("member_level") or 0
        if member_lvl >= min_lvl:
            return True, "member"
        return False, f"member_level_too_low (need {min_lvl}, have {member_lvl})"
    if perm.get("friends") and user_info.get("is_friend"):
        return True, "friend"
    if perm.get("followers") and user_info.get("is_follower"):
        return True, "follower"
    if perm.get("mods") and user_info.get("is_mod"):
        return True, "mod"

    return False, "no_permission"


@app.route("/api/tts/config", methods=["GET"])
def tts_get_config():
    """Get current TTS configuration."""
    return jsonify(_load_tts_config())

@app.route("/api/tts/config", methods=["POST"])
def tts_save_config():
    """Save TTS configuration."""
    cfg = request.get_json()
    if cfg:
        _save_tts_config(cfg)
    return jsonify({"status": "ok"})

@app.route("/api/tts/history", methods=["GET"])
def tts_get_history():
    """Get TTS history."""
    return jsonify(_load_tts_history())

@app.route("/api/tts/history/clear", methods=["POST"])
def tts_clear_history():
    """Clear TTS history."""
    _save_tts_history([])
    return jsonify({"status": "ok", "message": "History cleared"})

@app.route("/api/tts/voices", methods=["GET"])
def tts_get_voices():
    """Return available edge_tts voices for the frontend dropdown."""
    try:
        import edge_tts
        voices = _run_async(edge_tts.list_voices())
        # Return subset of fields the frontend needs
        return jsonify([{
            "ShortName": v.get("ShortName", ""),
            "FriendlyName": v.get("FriendlyName", v.get("ShortName", "")).replace("Microsoft ", ""),
            "Locale": v.get("Locale", ""),
            "Gender": v.get("Gender", "")
        } for v in voices])
    except Exception:
        # Fallback if edge_tts isn't available
        return jsonify([{
            "ShortName": "en-US-AriaNeural",
            "FriendlyName": "Aria (US)",
            "Locale": "en-US",
            "Gender": "Female"
        }])

@app.route("/api/tts/speak", methods=["POST"])
def tts_speak():
    """Receive TTS text, check permissions & config, generate speech, play via pygame."""
    try:
        return _tts_speak_impl()
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 200

def _tts_speak_impl():
    global _tts_last_at

    cfg = _load_tts_config()
    if not cfg.get("enabled", True):
        return jsonify({"status": "error", "message": "TTS is disabled"}), 403

    data = request.get_json()
    text = data.get("text", "").strip() if data else ""
    if not text:
        return jsonify({"status": "error", "message": "No text provided"}), 400

    effect = (data.get("effect") or "normal").lower().strip()
    if effect not in ("whisper", "yell", "normal"):
        effect = "normal"

    max_len = cfg.get("max_length", 200)
    if len(text) > max_len:
        return jsonify({"status": "error", "message": f"Text too long (max {max_len} chars)"}), 400

    # Permission check (skip for dashboard test)
    if not data.get("_test"):
        user_info = data.get("user_info", {})
        allowed, reason = _check_tts_permission(cfg, user_info)
        if not allowed:
            return jsonify({"status": "error", "message": f"Permission denied: {reason}"}), 403
    else:
        user_info = {}

    # Global cooldown
    global_cd = cfg.get("global_cooldown", 2)
    now = _time.time()
    if now - _tts_last_at < global_cd:
        return jsonify({"status": "skipped", "message": "Global TTS cooldown"}), 200
    _tts_last_at = now

    # Per-user cooldown
    uid = user_info.get("unique_id", "")
    per_user_cd = cfg.get("per_user_cooldown", 10)
    if uid and per_user_cd > 0:
        last = _tts_user_at.get(uid, 0)
        if now - last < per_user_cd:
            return jsonify({"status": "skipped", "message": "Your TTS cooldown"}), 200
        _tts_user_at[uid] = now

    nick = data.get("nick", "")
    voice = cfg.get("voice", "en-US-AriaNeural")
    speed = cfg.get("speed", "+0%")
    pitch = cfg.get("pitch", "+0Hz")

    def _play_tts():
        log_file = os.path.join(BASE_DIR, "tts_debug.log")
        out_file = None
        processed_file = None
        try:
            import edge_tts, traceback

            tts_dir = os.path.join(BASE_DIR, "tts")
            os.makedirs(tts_dir, exist_ok=True)
            out_file = os.path.join(tts_dir, f"tts_{int(_time.time())}.mp3")

            # edge_tts expects format like "+0%", "-10%", "+50%"
            rate = speed if speed and (speed.startswith("+") or speed.startswith("-")) else ("+" + speed)
            ptch = pitch  # edge_tts uses "+0Hz" format

            # Apply effect adjustments to rate/pitch (no SSML — just param changes)
            pygame_vol = 1.0
            effect_rate = rate
            effect_pitch = ptch

            if effect != "normal":
                try:
                    from tts_effects import get_effect_config
                    cfg = get_effect_config(effect)
                    pygame_vol = cfg.get("pygame_volume", 1.0)
                    # Merge base rate with effect rate offset
                    effect_rate = cfg.get("ssml_rate", rate)  # reuse rate offset
                    effect_pitch = cfg.get("ssml_pitch", ptch)
                except ImportError:
                    pass  # Fallback to normal if tts_effects not available

            async def _gen():
                communicate = edge_tts.Communicate(
                    text, voice, rate=effect_rate, pitch=effect_pitch
                )
                await communicate.save(out_file)

            _run_async(_gen())

            # Apply ffmpeg post-processing for enhanced effects
            if effect != "normal":
                try:
                    from tts_effects import apply_audio_effects
                    processed_file = apply_audio_effects(out_file, effect)
                except ImportError:
                    processed_file = out_file
            else:
                processed_file = out_file

            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)

            sound = pygame.mixer.Sound(processed_file)
            sound.set_volume(pygame_vol)
            sound.play()
            # Wait for playback to finish, then clean up temp files
            while pygame.mixer.get_busy():
                _time.sleep(0.1)
            try:
                os.remove(out_file)
            except Exception:
                pass
            if processed_file != out_file:
                try:
                    os.remove(processed_file)
                except Exception:
                    pass

            effect_tag = f" [{effect}]" if effect != "normal" else ""
            msg = f"[TTS]{effect_tag} {nick}: \"{text[:80]}\" ({len(text)} chars) | voice={voice} rate={rate} pitch={ptch}"
            print(msg)
            with open(log_file, "a") as f:
                f.write(msg + "\n")

            # Log to TTS history for dashboard
            uid = data.get("user_info", {}).get("unique_id", "") or nick or "unknown"
            entry = {
                "user": uid,
                "nick": nick or uid,
                "text": text[:500],  # Cap stored text
                "timestamp": _time.time(),
                "voice": voice,
                "effect": effect,
            }
            hist = _load_tts_history()
            hist.append(entry)
            _save_tts_history(hist)
        except Exception as e:
            err = f"[TTS ERROR] {e}\n{traceback.format_exc()}"
            print(err)
            with open(log_file, "a") as f:
                f.write(err + "\n")

    threading.Thread(target=_play_tts, daemon=True).start()
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    ensure_profiles_setup()
    # Start song queue worker for Spotify auto-play
    try:
        from spotify_handler import start_song_queue_worker
        start_song_queue_worker()
    except Exception as e:
        print(f"[SONG-QUEUE] Failed to start worker: {e}")
    app.run(host="0.0.0.0", port=5000, debug=True)
