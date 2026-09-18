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
from flask import Flask, render_template, request, jsonify, send_file, send_from_directory, abort
from werkzeug.utils import secure_filename
from event_registry import get_registry_for_api, get_registry_with_categories, get_event_categories
from actions import migrate_to_events_redesign, migrate_config_actions
import spotify_handler as sh
import gift_roulette
import copy
from utils import load_json, save_json, safe_json_read
from constants import *
from routes.spotify import spotify_bp
from routes.stats import stats_bp, init_stats_blueprint
from routes.overlay_settings import init_overlay_settings_blueprint
from routes.points import points_bp
from routes.addons import addons_api_bp, addons_page_bp, init_addons_blueprint
from routes.sociabuzz import create_sociabuzz_blueprint, load_or_create_webhook_settings
from routes.gift_card_studio import (
    create_gift_studio_assets_blueprint,
    create_gift_studio_blueprint,
)
import paths
import gift_catalog
import gift_catalog_sync
import gift_catalog_backfill
from addons.survival_rush.runtime.api import create_survival_rush_blueprint
from addons.survival_rush.runtime.service import SurvivalRushService
import addon_loader
import addon_runtime_registry
from sim_console_log import append_line as append_sim_console_line
from sim_console_log import clear_log as clear_sim_console_log
from sim_console_log import read_tail as read_sim_console_tail
from sim_console_log import append_line as append_bot_console_line
import bot_status as bot_status_mod
from gift_simulation import build_dashboard_sender, simulate_gift

# Centralized folderized path layout (release/config, release/data, release/logs, release/assets)
BASE_DIR = paths.BASE_DIR

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
app.register_blueprint(points_bp, url_prefix='/api/points')
app.register_blueprint(addons_api_bp, url_prefix='/api/addons')
app.register_blueprint(addons_page_bp)

_sociabuzz_settings = load_or_create_webhook_settings(
    paths.config("sociabuzz_webhook.json")
)
app.register_blueprint(
    create_sociabuzz_blueprint(
        secret=_sociabuzz_settings["path_secret"],
        expected_token=_sociabuzz_settings["webhook_token"],
        capture_path=paths.data("sociabuzz_webhook_capture.json"),
    )
)

survival_rush_service = SurvivalRushService(
    paths.addons("survival_rush"),
)
app.register_blueprint(
    create_survival_rush_blueprint(survival_rush_service),
    url_prefix="/api/addons/survival-rush/objective-rush",
)
_survival_addon = addon_loader.load_addon("survival_rush")
addon_runtime_registry.register(
    "survival_rush",
    survival_rush_service,
    enabled=bool(_survival_addon and _survival_addon.get("enabled", False)),
)
if _survival_addon:
    addon_runtime_registry.set_config(
        "survival_rush", _survival_addon.get("config") or {}
    )
atexit.register(addon_runtime_registry.unregister, "survival_rush")

# Gift Card Studio — overlay card designer. The catalog is read at request time
# via load_config (defined below) so newly configured gifts appear without an
# app restart; the lambda defers the lookup instead of capturing a stale dict.
app.register_blueprint(
    create_gift_studio_blueprint(
        data_dir=paths.DATA_DIR,
        assets_dir=paths.ASSETS_DIR,
        load_config=lambda: load_config(),
        base_dir=paths.BASE_DIR,
    ),
    url_prefix="/api/gift-studio",
)
app.register_blueprint(create_gift_studio_assets_blueprint(paths.DATA_DIR))

# Initialize blueprints with runtime directories
init_stats_blueprint(paths.DATA_DIR)
init_overlay_settings_blueprint(paths.DATA_DIR)
init_addons_blueprint(paths.ADDONS_DIR)

# Long-term viewer points DB (SQLite) — create schema early so the dashboard
# tab works even before the first gift arrives.
import points_store
points_store.init(paths.data("points.db"))

CONFIG_FILE = paths.config("config.yml")
PROFILES_DIR = os.path.join(paths.CONFIG_DIR, "profiles")
ACTIVE_PROFILE_FILE = paths.config("active_profile.txt")


def _safe_profile_name(value):
    """Validate a profile display name before joining it to PROFILES_DIR."""
    name = str(value or "").strip()
    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or ":" in name
        or os.path.basename(name) != name
    ):
        raise ValueError("Invalid profile name")
    return name


bot_process = None
bot_logs = []
_bot_logs_lock = threading.Lock()
MAX_LOGS = 0  # 0 = unlimited
_external_bot_scan_cache = {"ts": 0.0, "items": []}


def _hidden_subprocess_kwargs():
    """Hide Windows helper subprocesses used by status/stop polling."""
    if os.name != 'nt':
        return {}
    kwargs = {"creationflags": getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)}
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= getattr(subprocess, 'STARTF_USESHOWWINDOW', 1)
        startupinfo.wShowWindow = getattr(subprocess, 'SW_HIDE', 0)
        kwargs["startupinfo"] = startupinfo
    except Exception:
        pass
    return kwargs


def _is_local_bot_running():
    return bot_process is not None and bot_process.poll() is None


def _process_matches_current_install(command_line: str) -> bool:
    """Avoid confusing release_test/dist/other copies with this launcher."""
    cmd = (command_line or "").replace('\\\\', '/').replace('\\', '/').lower()
    if "--run-bot" not in cmd:
        return False
    if getattr(sys, 'frozen', False):
        base = os.path.abspath(BASE_DIR).replace('\\\\', '/').replace('\\', '/').lower()
        return base in cmd
    # Dev/source mode: only consider this project tree.
    return "main.py" in cmd or "tiktokmcintegrator" in cmd


def _list_external_bot_processes(force=False):
    """Find orphan/background --run-bot processes not owned by app.bot_process."""
    now = _time.time()
    if not force and now - _external_bot_scan_cache.get("ts", 0.0) < 1.0:
        return list(_external_bot_scan_cache.get("items", []))

    local_pid = None
    local_proc = bot_process
    if local_proc is not None and local_proc.poll() is None:
        try:
            local_pid = int(local_proc.pid)
        except Exception:
            local_pid = None
    current_pid = os.getpid()
    items = []

    try:
        if os.name == 'nt':
            ps_script = (
                "$ErrorActionPreference='SilentlyContinue'; "
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.CommandLine -like '*--run-bot*' } | "
                "Select-Object ProcessId,ParentProcessId,Name,CommandLine | "
                "ConvertTo-Json -Compress"
            )
            out = subprocess.check_output(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=4,
                **_hidden_subprocess_kwargs(),
            ).strip()
            if out:
                raw = json.loads(out)
                if isinstance(raw, dict):
                    raw = [raw]
                for row in raw or []:
                    pid = int(row.get("ProcessId") or 0)
                    cmd = row.get("CommandLine") or ""
                    if pid and pid not in (current_pid, local_pid) and _process_matches_current_install(cmd):
                        items.append({
                            "pid": pid,
                            "ppid": int(row.get("ParentProcessId") or 0),
                            "name": row.get("Name") or "",
                            "command": cmd,
                        })
        else:
            out = subprocess.check_output(
                ["ps", "-eo", "pid=,ppid=,args="],
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=4,
            )
            for line in out.splitlines():
                parts = line.strip().split(None, 2)
                if len(parts) < 3:
                    continue
                pid, ppid, cmd = int(parts[0]), int(parts[1]), parts[2]
                if pid not in (current_pid, local_pid) and _process_matches_current_install(cmd):
                    items.append({"pid": pid, "ppid": ppid, "name": "", "command": cmd})
    except Exception as e:
        print(f"Bot process scan failed: {e}")
        items = []

    _external_bot_scan_cache["ts"] = now
    _external_bot_scan_cache["items"] = list(items)
    return items


def is_any_bot_running():
    """Return (any_running, local_running, external_processes)."""
    local_running = _is_local_bot_running()
    external = _list_external_bot_processes()
    return bool(local_running or external), local_running, external


def _terminate_external_bot_process(pid: int) -> bool:
    try:
        if os.name == 'nt':
            result = subprocess.run(
                ["taskkill.exe", "/PID", str(int(pid)), "/T", "/F"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                **_hidden_subprocess_kwargs(),
            )
            return result.returncode == 0
        import signal
        os.kill(int(pid), signal.SIGTERM)
        deadline = _time.time() + 5
        while _time.time() < deadline:
            try:
                os.kill(int(pid), 0)
            except OSError:
                return True
            _time.sleep(0.2)
        os.kill(int(pid), signal.SIGKILL)
        return True
    except Exception as e:
        print(f"Failed to terminate external bot PID {pid}: {e}")
        return False


def stop_all_bots():
    """Stop local bot handle plus orphan/background --run-bot processes."""
    global bot_process
    stopped = []
    local_proc = bot_process
    if local_proc is not None and local_proc.poll() is None:
        try:
            pid = int(local_proc.pid)
            local_proc.terminate()
            try:
                local_proc.wait(timeout=8)
            except Exception:
                local_proc.kill()
                local_proc.wait(timeout=5)
            stopped.append(pid)
        except Exception as e:
            print(f"Failed to stop local bot: {e}")
        finally:
            bot_process = None

    for proc in _list_external_bot_processes(force=True):
        pid = proc.get("pid")
        if pid and _terminate_external_bot_process(pid):
            stopped.append(int(pid))

    _external_bot_scan_cache["ts"] = 0.0
    _external_bot_scan_cache["items"] = []
    return stopped


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
    signal_file = paths.data(".reload_signal")
    try:
        with open(signal_file, "w") as f:
            f.write("1")
        print("--- Config reload signaled to bot ---")
    except Exception as e:
        print(f"Failed to signal config reload: {e}")

BOT_CONSOLE_LOG = "bot_console.log"
_BOT_CONSOLE_MAX_BYTES = 2_000_000
_BOT_CONSOLE_KEEP_LINES = 3_000


def _persist_bot_console(line):
    """Mirror the bot's stdout to a bounded file in logs/.

    The in-memory console list dies with this process, so a finished session
    could not be diagnosed afterwards — exactly the case when TikTok events went
    stale and the operator needed the reconnect history. Each persisted line
    carries a wall-clock stamp: without one, a drop could be read but never
    timed, and "how long was it up before it died" is the number that separates
    a flaky link from an unusable one. Never raises: losing a log line must not
    cost the dashboard its live console.
    """
    if not line:
        return
    try:
        stamped = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {line}"
        append_bot_console_line(
            paths.logs(BOT_CONSOLE_LOG),
            stamped,
            max_bytes=_BOT_CONSOLE_MAX_BYTES,
            keep_lines=_BOT_CONSOLE_KEEP_LINES,
        )
    except Exception:
        pass


def read_output(pipe):
    global bot_logs
    # Session separator so logs/bot_console.log stays readable across restarts.
    # (The persisted-line stamp supplies the time.)
    _persist_bot_console("--- Bot session started ---")
    for line in iter(pipe.readline, ''):
        stripped = line.strip()
        with _bot_logs_lock:
            bot_logs.append(stripped)
            if MAX_LOGS > 0 and len(bot_logs) > MAX_LOGS:
                bot_logs.pop(0)
        _persist_bot_console(stripped)

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
        stats_file = paths.data("viewer_stats.json")
        try:
            with open(stats_file, "w", encoding="utf-8") as f:
                json.dump({"viewers": 0, "total_viewers": 0}, f)
        except Exception:
            pass

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    """Native launcher readiness probe."""
    return jsonify({"status": "ok"})

@app.route("/api/config", methods=["GET"])
def get_config():
    resp = jsonify(load_config())
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp

@app.route("/api/config", methods=["POST"])
def update_config():
    data = request.json
    # Roulette owns its own save endpoint. General settings may carry a stale
    # browser snapshot; never let it overwrite independent prizes.
    existing_roulette = (load_config().get("Roulette") or {})
    if "prizes" in existing_roulette:
        data["Roulette"] = existing_roulette
    save_config(data)
    # Signal hot-reload if any bot process is running (including orphan/background).
    if is_any_bot_running()[0]:
        signal_reload()
    return jsonify({"status": "success", "message": "Configuration saved!"})


# ── Gift Roulette config + test spin (plan: .hermes/plans/roulette-randomizer.md) ──

_ROULETTE_STATE_PATH = paths.data("roulette_state.json")


@app.route("/api/roulette/config", methods=["GET"])
def get_roulette_config():
    """Normalized Roulette block plus pool validation for the dashboard panel."""
    config = load_config()
    normalized = gift_roulette.normalize_config(config.get("Roulette"))
    gifts = migrate_config_actions(copy.deepcopy(config)).get("Gifts", {})
    catalog_rows = safe_json_read(paths.data("available_gifts.json"))
    catalog_by_id = gift_roulette.build_catalog_index(
        catalog_rows if isinstance(catalog_rows, list) else []
    )
    if "prizes" not in normalized:
        normalized = gift_roulette.migrate_prize_config(config, catalog_by_id)
        config["Roulette"] = normalized
        save_config(config)
        if is_any_bot_running()[0]:
            signal_reload()
    entries = gift_roulette.resolve_entries(
        normalized, gifts,
        config.get("GiftNames", {}) or {}, config.get("GiftDescriptions", {}) or {},
        catalog_by_id,
    )
    gift_templates = []
    for gid, bundle in gifts.items():
        if str(gid) == "GlobalActions" or not isinstance(bundle, list) or not bundle:
            continue
        gid = str(gid)
        display = gift_roulette.resolve_entries({"pool": [gid]}, gifts,
            config.get("GiftNames", {}) or {}, config.get("GiftDescriptions", {}) or {}, catalog_by_id)
        if display:
            template = display[0]
            template["actions"] = copy.deepcopy(bundle)
            template["gift_name"] = (config.get("GiftNames") or {}).get(gid) or (catalog_by_id.get(gid) or {}).get("name") or template["label"]
            gift_templates.append(template)
    warnings = []
    valid_ids = {e["gift_id"] for e in entries}
    for gift_id in ([] if "prizes" in normalized else normalized["pool"]):
        if gift_id not in valid_ids:
            warnings.append(f"Pool entry {gift_id} is not a configured gift with actions")
    if normalized["enabled"] and len(valid_ids) < 2:
        warnings.append("Enable requires at least 2 valid pool entries")
    if normalized["trigger_gift_id"]:
        warnings.append(
            "Legacy trigger gift is unused — attach a Roulette action on any gift or event instead"
        )

    resp = jsonify({
        "roulette": normalized,
        "resolved_entries": entries,
        "gift_templates": gift_templates,
        "warnings": warnings,
    })
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


@app.route("/api/roulette/config", methods=["PUT"])
def update_roulette_config():
    """Replace ONLY the Roulette block of the active profile. Nothing else.

    Accepts just the normalized Roulette fields — never action bundles or
    arbitrary config — then saves through the existing save_config path so the
    active profile copy stays in sync, and signals hot-reload.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"message": "Roulette config must be an object"}), 400
    if "prizes" in payload:
        try:
            payload["prizes"] = gift_roulette.validate_prizes(payload["prizes"])
        except (ValueError, TypeError) as exc:
            return jsonify({"message": str(exc)}), 400
    normalized = gift_roulette.normalize_config(payload)

    config = load_config()
    if "prizes" in (config.get("Roulette") or {}) and "prizes" not in payload:
        return jsonify({"message": "Reload Roulette before saving: this profile now uses independent prizes"}), 409
    gifts = migrate_config_actions(copy.deepcopy(config)).get("Gifts", {})
    catalog_rows = safe_json_read(paths.data("available_gifts.json"))
    catalog_by_id = gift_roulette.build_catalog_index(
        catalog_rows if isinstance(catalog_rows, list) else []
    )
    entries = gift_roulette.resolve_entries(
        normalized, gifts,
        config.get("GiftNames", {}) or {}, config.get("GiftDescriptions", {}) or {},
        catalog_by_id,
    )

    # NEVER discard the user's save. Invalid-enable does not 400: it persists
    # everything with enabled=False and returns a warning the panel shows.
    warnings = []
    if normalized["enabled"] and len(entries) < 2:
        warnings.append("Needs at least 2 valid pool entries — Roulette saved but left disabled")
        normalized["enabled"] = False
    for gift_id in ([] if "prizes" in normalized else normalized["pool"]):
        if gift_id not in {e["gift_id"] for e in entries}:
            warnings.append(f"Pool entry {gift_id} is not a configured gift with actions")

    config["Roulette"] = normalized
    save_config(config)
    if is_any_bot_running()[0]:
        signal_reload()
    resp = jsonify({"status": "success", "roulette": normalized, "warnings": warnings})
    if warnings:
        resp.status_code = 200
    return resp


# The dashboard test-spin runtime MUST be a process-level singleton. Building a
# fresh RouletteRuntime per HTTP request gave each request its own empty queue,
# so a second/third rapid Test Spin was enqueued into a queue that was thrown
# away when the request ended — the spin silently vanished. One runtime per
# dashboard process keeps the FIFO alive across requests.
_DASHBOARD_ROULETTE_RUNTIME = None
_DASHBOARD_ROULETTE_LOCK = threading.Lock()


def _dashboard_roulette_runtime():
    """Return the dashboard's shared RouletteRuntime, creating it once."""
    global _DASHBOARD_ROULETTE_RUNTIME
    with _DASHBOARD_ROULETTE_LOCK:
        if _DASHBOARD_ROULETTE_RUNTIME is None:
            runtime = gift_roulette.RouletteRuntime(_ROULETTE_STATE_PATH)
            runtime.sweep_stale()
            _DASHBOARD_ROULETTE_RUNTIME = runtime
        return _DASHBOARD_ROULETTE_RUNTIME


# Rejection reasons are not interchangeable: "wait for the cooldown" is wrong
# advice for a duplicate summary or a full queue, and it sent the operator
# hunting for a cooldown that was not the problem.
_ROULETTE_REJECT_MESSAGES = {
    "duplicate_final": (
        "This gift + viewer already spun in the last 30 seconds — TikTok "
        "re-sent the same completion, so it was not spun again."
    ),
    "queue_full": (
        "The spin queue is full. Wait for the queued spins to finish, then try again."
    ),
    "invalid_pool": (
        "The roulette pool has no valid gift. Fix the pool in the Roulette tab."
    ),
}


def _roulette_reject_message(reason: str) -> str:
    """Operator-facing explanation for a rejected spin."""
    return _ROULETTE_REJECT_MESSAGES.get(
        reason,
        f"Spin rejected: {reason}. Wait for the current spin to finish.",
    )


@app.route("/api/roulette/test", methods=["POST"])
def test_roulette_spin():
    """Executable test spin — dashboard process ONLY while the bot is stopped.

    The bot and dashboard are separate processes with independent in-memory
    runtimes; a test spin while the bot is live could interleave state writes
    and double-fire Minecraft actions. Live testing uses a Roulette action
    on a gift or event.
    """
    if is_any_bot_running()[0]:
        return jsonify({
            "status": "error",
            "message": "Stop the bot before running an executable Test Spin. "
                       "While live, attach a Roulette action on a gift or event instead.",
        }), 409

    payload = request.get_json(silent=True) or {}
    user = str(payload.get("user") or "TestViewer").strip()[:100] or "TestViewer"

    config = load_config()
    config = migrate_config_actions(config)  # legacy string lists must not no-op
    normalized = gift_roulette.normalize_config(config.get("Roulette"))
    if not normalized["enabled"]:
        return jsonify({"status": "error", "message": "Roulette is disabled"}), 400

    gifts = config.get("Gifts", {})
    catalog_rows = safe_json_read(paths.data("available_gifts.json"))
    catalog_by_id = gift_roulette.build_catalog_index(
        catalog_rows if isinstance(catalog_rows, list) else []
    )

    settings = config.get("Settings") or {}
    trigger_ctx = {
        "gift_id": normalized["trigger_gift_id"],
        "gift_name": "Test Trigger",
        "repeat_count": "1",
        "total_coin": "0",
        "user": user,
        "mc": str(settings.get("MinecraftUsername") or ""),
        "amount": "1",
        "asset_url": "",
    }

    try:
        prepared = gift_roulette.prepare_spin(
            normalized, gifts,
            config.get("GiftNames", {}) or {}, config.get("GiftDescriptions", {}) or {},
            catalog_by_id, trigger_ctx,
            source="test", profile=get_active_profile(),
        )
    except gift_roulette.RouletteValidationError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    runtime = _dashboard_roulette_runtime()
    accepted, reason = runtime.try_reserve(
        prepared, int(normalized.get("cooldown_ms", 2000))
    )
    if not accepted:
        return jsonify({
            "status": "error",
            "reason": reason,
            "message": _roulette_reject_message(reason),
        }), 409

    queued = reason == "queued"
    if not queued:
        runtime.mark_reserved_started()

    # Submit the landing to the shared background loop; do NOT block this HTTP
    # request for the full spin duration (mirror of the TTS loop pattern).
    from gift_simulation import build_dashboard_sender
    log_sink = lambda message: None  # noqa: E731

    async def _run_test_spin():
        sender = build_dashboard_sender(config, log=log_sink)

        async def bundle(actions, context):
            from actions import execute_actions as _exec
            await _exec(actions, context, sender)

        async def drain():
            """Run spins queued behind the active one, FIFO.

            A second/third rapid Test Spin must still fire. Without this chain
            the queued spin sat in the FIFO forever, because nothing drains the
            dashboard's queue.
            """
            if not runtime.claim_pump():
                return
            try:
                while True:
                    nxt = runtime.take_next()
                    if nxt is None:
                        delay = runtime.cooldown_delay()
                        if delay > 0 and runtime.queue_depth() > 0:
                            await _asyncio.sleep(delay)
                            continue
                        return
                    runtime.mark_reserved_started()
                    await runtime.run_reserved(nxt, bundle)
            finally:
                runtime.release_pump()

        if queued:
            # Already appended to the FIFO by try_reserve — do NOT run it here.
            # Pump only in case no chain is live (e.g. the previous spin already
            # finished and only cooldown was pending).
            await drain()
            return
        try:
            await runtime.run_reserved(prepared, bundle)
        finally:
            await drain()

    _submit_async(_run_test_spin())

    resp = jsonify({
        "status": "accepted",
        "queued": queued,
        "queue_depth": runtime.queue_depth(),
        "spin_id": prepared.spin_id,
        "winner": prepared.winner_label,
        # Roll/hold durations so the dashboard's audio mirror can space queued
        # spins correctly (it needs the same spin_ms/hold_ms the server uses).
        "spin_ms": normalized.get("spin_ms"),
        "hold_ms": normalized.get("hold_ms"),
        # A queued spin has no honest landing time yet: it is stamped when the
        # drain chain activates it. Report null instead of a stale estimate.
        "lands_at": None if queued else prepared.public_state["lands_at"],
        "hide_at": None if queued else prepared.public_state["hide_at"],
    })
    resp.headers["Cache-Control"] = "no-store"
    return resp, 202


@app.route("/api/test-connection", methods=["POST"])
def test_connection():
    """Test Minecraft connection based on posted connector form values.

    The settings UI may have unsaved changes. Do not read only config.yml here,
    otherwise selecting Forge/ServerTap still tests the previously-saved RCON
    config and every error says port 25575.
    """
    import yaml
    import requests as _requests
    from paths import config as _config_path

    payload = request.get_json(silent=True) or {}
    cfg = {}
    with open(_config_path("config.yml"), "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    ctype = payload.get("connector_type") or cfg.get("Settings", {}).get("ConnectorType", "rcon")

    if ctype == "servertap":
        st = payload.get("servertap") or cfg.get("ServerTap", {})
        host = st.get("Host", "127.0.0.1")
        port = st.get("Port", 4567)
        api_key = st.get("ApiKey", "")
        try:
            r = _requests.post(
                f"http://{host}:{port}/api/execute",
                json={"apiKey": api_key, "command": "list"},
                timeout=10
            )
            if r.status_code == 200:
                return jsonify({"status": "success", "message": f"ServerTap connected! ({host}:{port})"})
            elif r.status_code == 401:
                return jsonify({"status": "error", "message": "Auth failed - check ApiKey"})
            else:
                return jsonify({"status": "error", "message": f"HTTP {r.status_code}"})
        except _requests.exceptions.ConnectionError:
            return jsonify({"status": "error", "message": f"Cannot connect to {host}:{port} - is ServerTap running?"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})

    elif ctype == "forge":
        fg = payload.get("forge") or cfg.get("Forge", {})
        host = fg.get("Host", "127.0.0.1")
        port = fg.get("Port", 5942)
        password = fg.get("Password", "")
        try:
            r = _requests.post(
                f"http://{host}:{port}/command",
                json={"password": password, "command": "list"},
                timeout=10
            )
            if r.status_code == 200:
                return jsonify({"status": "success", "message": f"Forge Mod connected! ({host}:{port})"})
            else:
                return jsonify({"status": "error", "message": f"HTTP {r.status_code}"})
        except _requests.exceptions.ConnectionError:
            return jsonify({"status": "error", "message": f"Cannot connect to {host}:{port} - is Forge mod running?"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})

    else:  # rcon
        rc = payload.get("rcon") or cfg.get("Rcon", {})
        host = rc.get("Host", "127.0.0.1")
        port = rc.get("Port", 25575)
        password = rc.get("Password", "")
        try:
            from mcrcon import MCRcon
            with MCRcon(host, password, port=port) as mcr:
                resp = mcr.command("list")
            return jsonify({"status": "success", "message": f"RCON connected! ({host}:{port})"})
        except Exception as e:
            return jsonify({"status": "error", "message": f"Cannot connect to {host}:{port} - {str(e)}"})


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
    resp = jsonify({"profiles": profiles, "active": get_active_profile()})
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp

@app.route("/api/profiles/switch", methods=["POST"])
def switch_profile():
    try:
        name = _safe_profile_name((request.get_json(silent=True) or {}).get("profile"))
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid profile name"}), 400
    profile_path = os.path.join(PROFILES_DIR, f"{name}.yml")
    if os.path.exists(profile_path):
        shutil.copy(profile_path, CONFIG_FILE)
        set_active_profile(name)
        # Signal hot-reload if any bot process is running (including orphan/background).
        if is_any_bot_running()[0]:
            signal_reload()
        return jsonify({"status": "success", "message": f"Switched to profile: {name}"})
    return jsonify({"status": "error", "message": "Profile not found"}), 404

@app.route("/api/profiles/create", methods=["POST"])
def create_profile():
    payload = request.get_json(silent=True) or {}
    try:
        name = _safe_profile_name(payload.get("profile"))
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid profile name"}), 400
    duplicate = payload.get("duplicate", False)
        
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
    try:
        name = _safe_profile_name(name)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid profile name"}), 400
    if name == get_active_profile():
        return jsonify({"status": "error", "message": "Cannot delete active profile"}), 400
        
    profile_path = os.path.join(PROFILES_DIR, f"{name}.yml")
    if os.path.exists(profile_path):
        os.remove(profile_path)
        return jsonify({"status": "success", "message": "Profile deleted"})
    return jsonify({"status": "error", "message": "Profile not found"}), 404

@app.route("/api/profiles/<name>/export", methods=["GET"])
def export_profile(name):
    try:
        name = _safe_profile_name(name)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid profile name"}), 400
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

@app.route('/gift_assets/<path:fname>')
def serve_gift_asset(fname):
    """Serve downloaded gift animation assets (video/Lottie)."""
    # Reject path traversal
    if '..' in fname or fname.startswith('/') or fname.startswith('\\\\'):
        abort(404)
    gift_assets_dir = paths.assets('gift_assets')
    if not os.path.exists(os.path.join(gift_assets_dir, fname)):
        abort(404)
    return send_from_directory(gift_assets_dir, fname, as_attachment=False)

@app.route('/avatar_cache/<path:fname>')
def serve_avatar_cache(fname):
    """Serve locally cached TikTok profile pictures for overlays."""
    if '..' in fname or fname.startswith('/') or fname.startswith('\\\\'):
        abort(404)
    avatar_dir = os.path.join(paths.ASSETS_DIR, 'avatar_cache')
    full_path = os.path.abspath(os.path.join(avatar_dir, fname))
    root = os.path.abspath(avatar_dir)
    if os.path.commonpath([root, full_path]) != root or not os.path.exists(full_path):
        abort(404)
    return send_from_directory(avatar_dir, os.path.basename(fname), as_attachment=False, max_age=86400)

@app.route('/api/gifts/available', methods=['GET'])
def get_available_gifts():
    """Serve the union-merged gift catalog.

    TikTok's /gift/list/ is only the room panel (verified: 701 of 2783 gifts,
    is_full_gift_data=False), so this endpoint serves the merged cache that also
    holds region-synced and event-learned gifts. A live fetch here only ever
    MERGES into that cache — it must never overwrite it, or gifts that exist
    solely in Khito's room (Super GG, KhitoFam) would be deleted.
    """
    gifts_file = paths.data("available_gifts.json")
    cached = gift_catalog.load_catalog(gifts_file)

    # Panel scope: the picker's precise default — only gifts TikTok currently
    # offers in this room. Room scope remains available for callers that need
    # current-panel plus previously received gifts. Full scope stays unchanged.
    if cached and request.args.get("scope") == "panel":
        cached = [e for e in cached if e.get("in_panel")]
    elif cached and request.args.get("scope") == "room":
        cached = [e for e in cached if e.get("in_panel") or e.get("seen")]

    # A populated cache is authoritative; refreshing is an explicit action via
    # /api/gifts/refresh so the dashboard never blocks on TikTok.
    if cached:
        return jsonify(cached)

    try:
        import requests as req
        params = {
            "aid": "1988",
            "app_name": "tiktok_web",
            "device_platform": "web",
            "browser_language": "en",
            "browser_name": "Mozilla",
            "browser_online": "true",
            "browser_platform": "Win32",
            "browser_version": "5.0",
            "cookie_enabled": "true",
            "screen_width": "1920",
            "screen_height": "1080",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://www.tiktok.com/",
            "Origin": "https://www.tiktok.com",
        }
        resp = req.get("https://webcast.tiktok.com/webcast/gift/list/", params=params, headers=headers, timeout=10)
        raw = resp.json().get("data", {})
        gift_catalog.merge_into_catalog(gifts_file, raw.get("gifts", []), source="panel")
        return jsonify(gift_catalog.load_catalog(gifts_file))
    except Exception as e:
        if cached:
            return jsonify(cached)
        return jsonify({"error": f"Could not fetch gifts: {str(e)}"}), 500


@app.route('/api/gifts/simulate', methods=['POST'])
def simulate_configured_gift():
    """Run global and gift-specific actions without fabricating a TikTok event."""
    data = request.get_json(silent=True) or {}
    config = load_config()
    gift_key = str(data.get("gift_key") or "").strip()

    catalog_entry = None
    for entry in gift_catalog.load_catalog(paths.data("available_gifts.json")):
        if str(entry.get("id") or "") == gift_key:
            catalog_entry = entry
            break

    def log(message):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        append_sim_console_line(paths.logs("sim_console.log"), f"[{ts}] {message}")

    try:
        result = _run_async(simulate_gift(
            config,
            gift_key=gift_key,
            user=data.get("user"),
            amount=data.get("amount"),
            gift_meta=catalog_entry,
            send_mc_command=build_dashboard_sender(config, log=log),
        ))
        for action_type in result.get("skipped_actions") or []:
            log(f"[SKIP] '{action_type}' action not run by the simulator — "
                f"use Roulette tab → Test Spin.")
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        log(f"[ERR] gift simulation failed: {exc}")
        return jsonify({"error": str(exc)}), 502


@app.route('/api/gifts/refresh', methods=['POST'])
def refresh_available_gifts():
    """Rebuild the gift catalog from every available source.

    Sources are unioned, never replaced:
      1. TikTok's public /gift/list/ (the room-agnostic web panel)
      2. EulerStream's per-region panels (recovers region-locked gifts such as
         Game Controller 6581/7569, absent from Indonesia's panel)
      3. EulerStream's full gift catalog, 2783 rows (recovers gifts retired from
         every live panel: Spirit of 45, Live Up, Fighting, Spark ring)
      4. Local history — gift_log.json + points.db (recovers gifts in NO
         catalog anywhere, e.g. Super GG 12988 and the custom KhitoFam 938882)

    Event-learned gifts already in the cache always survive.
    """
    gifts_file = paths.data("available_gifts.json")
    before = len(gift_catalog.load_catalog(gifts_file))
    result = {
        "before": before, "panel": {}, "regions": {}, "euler_catalog": {},
        "history": {}, "errors": [],
    }

    try:
        import requests as req
        params = {
            "aid": "1988", "app_name": "tiktok_web", "device_platform": "web",
            "browser_language": "en", "browser_name": "Mozilla", "browser_online": "true",
            "browser_platform": "Win32", "browser_version": "5.0", "cookie_enabled": "true",
            "screen_width": "1920", "screen_height": "1080",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://www.tiktok.com/",
            "Origin": "https://www.tiktok.com",
        }
        resp = req.get("https://webcast.tiktok.com/webcast/gift/list/", params=params, headers=headers, timeout=15)
        panel = (resp.json().get("data") or {}).get("gifts", [])
        result["panel"] = gift_catalog.merge_into_catalog(gifts_file, panel, source="panel")
        result["panel"]["fetched"] = len(panel)
    except Exception as e:
        result["errors"].append(f"TikTok panel: {e}")

    try:
        cfg = load_config() or {}
        api_key = str((cfg.get("Settings") or {}).get("EulerApiKey", "") or "")
        result["regions"] = gift_catalog_sync.sync_regions(gifts_file, api_key)
        if result["regions"].get("error"):
            result["errors"].append(f"Region sync: {result['regions']['error']}")
        result["euler_catalog"] = gift_catalog_sync.sync_euler_catalog(gifts_file, api_key)
        if result["euler_catalog"].get("error"):
            result["errors"].append(f"Euler catalog: {result['euler_catalog']['error']}")
    except Exception as e:
        result["errors"].append(f"Region sync: {e}")

    try:
        result["history"] = gift_catalog_backfill.backfill_all(
            gifts_file, paths.data("gift_log.json"), paths.data("points.db")
        )
    except Exception as e:
        result["errors"].append(f"History backfill: {e}")

    result["after"] = len(gift_catalog.load_catalog(gifts_file))
    result["added"] = result["after"] - before
    result["status"] = "ok" if result["after"] > 0 else "error"
    return jsonify(result), (200 if result["after"] > 0 else 500)

@app.route("/api/bot/start", methods=["POST"])
def start_bot():
    global bot_process, bot_logs
    any_running, local_running, external = is_any_bot_running()
    if any_running:
        return jsonify({
            "status": "warning",
            "message": "Bot is already running in the background!" if external and not local_running else "Bot is already running!",
            "running": True,
            "local": local_running,
            "external": bool(external),
            "external_pids": [p.get("pid") for p in external],
        })

    bot_cmd = []
    try:
        bot_logs.clear()

        # Force UTF-8 encoding for Python subprocess to prevent emoji crashes
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"  # Fix output buffering for the packaged exe

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
            **_hidden_subprocess_kwargs(),
        )
        _external_bot_scan_cache["ts"] = 0.0
        _external_bot_scan_cache["items"] = []

        # Start a thread to read output so the buffer doesn't fill up and freeze the bot
        t = threading.Thread(target=read_output, args=(bot_process.stdout,))
        t.daemon = True
        t.start()

        return jsonify({"status": "success", "message": "Bot started!", "running": True, "local": True, "external": False})
    except Exception as e:
        return jsonify({"status": "error", "message": f"{str(e)} (Command: {bot_cmd})"}), 500

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
    reports_dir = paths.assets("reports")
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
    stopped = stop_all_bots()
    if stopped:
        # Generate post-stream report
        try:
            generate_report()
        except Exception as e:
            print(f"Report generation failed: {e}")
        bot_logs.append("--- Bot Terminated ---")
        # Zero out viewer stats so dashboard doesn't show stale data
        stats_file = paths.data("viewer_stats.json")
        try:
            with open(stats_file, "w", encoding="utf-8") as f:
                json.dump({"viewers": 0, "total_viewers": 0}, f)
        except Exception:
            pass
        return jsonify({"status": "success", "message": "Bot stopped!", "stopped_pids": stopped})
    return jsonify({"status": "warning", "message": "Bot is not running!"})

@app.route("/api/bot/status", methods=["GET"])
def bot_status():
    _running, local_running, external = is_any_bot_running()
    external_pids = [p.get("pid") for p in external]
    running = bool(local_running or external)
    
    # Load current settings to show LogOnlyMode/DebugMode state
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                c = yaml.safe_load(f) or {}
            _current_settings = c.get("Settings", {})
        else:
            _current_settings = {}
    except Exception:
        _current_settings = {}
    
    status = bot_status_mod.read_status(paths)

    # Derive the display state:
    #  - Process dead + no state file   -> offline (never started)
    #  - Process dead + last state was 'ended'/'stopped' -> offline (clean stop)
    #  - Process dead + last state was 'failed'          -> failed (retries exhausted)
    #  - Process dead otherwise                          -> offline (crashed/ended)
    #  - Process alive -> trust the state file, fall back to "connecting" if stale.
    state = status.get("state")
    ts = status.get("ts")
    
    # Don't treat connected/disconnected/ended/stopped as stale ever — those are terminal
    # states that don't need heartbeats. Only flag transient states (starting/connecting/reconnecting)
    # as potentially stale, and give them 60s instead of 30s to avoid flappy UI.
    is_transient_state = state in ("starting", "connecting", "reconnecting")
    stale = ts is None or (is_transient_state and (_time.time() - ts) > 60)

    if running:
        if not state or stale:
            derived = "connecting"
        else:
            derived = state
    else:
        if state in ("failed",):
            derived = "failed"
        else:
            derived = "offline"

    return jsonify({
        "running": running,
        "state": derived,
        "local": local_running,
        "external": bool(external),
        "external_pids": external_pids,
        "pid": bot_process.pid if local_running and bot_process is not None else (external_pids[0] if external_pids else None),
        "room_id": status.get("room_id"),
        "username": status.get("username"),
        "error": status.get("error"),
        "attempt": status.get("attempt"),
        "max_attempts": status.get("max_attempts"),
        "settings": _current_settings,  # Include LogOnlyMode/DebugMode state
    })

@app.route("/api/bot/logs", methods=["GET"])
def bot_logs_endpoint():
    """Return bot console logs."""
    with _bot_logs_lock:
        return jsonify({"logs": list(bot_logs)})

@app.route("/api/bot/logs/clear", methods=["POST"])
def clear_bot_logs_endpoint():
    """Clear the dashboard's in-memory bot console history."""
    with _bot_logs_lock:
        bot_logs.clear()
    return jsonify({"ok": True})

@app.route("/api/console/logs", methods=["GET"])
def sim_console_logs_endpoint():
    """Return simulated Minecraft console log (commands sent + responses).

    Reads from the shared sim_console.log file in BASE_DIR. Both the dashboard
    (this endpoint) and the bot (minecraftDiamond._sim_console_push) write
    here when running. The log is shared across processes so we don't need
    to import the bot's modules in the dashboard.
    """
    log_path = paths.logs("sim_console.log")
    try:
        snapshot = read_sim_console_tail(log_path, max_lines=500)
        return jsonify({"logs": snapshot.lines, "revision": snapshot.revision})
    except Exception:
        return jsonify({"logs": [], "revision": "error"})

@app.route("/api/console/clear", methods=["POST"])
def sim_console_clear_endpoint():
    """Clear the simulated Minecraft console log."""
    log_path = paths.logs("sim_console.log")
    try:
        clear_sim_console_log(log_path)
    except Exception:
        pass
    return jsonify({"ok": True})

@app.route("/api/console/send", methods=["POST"])
def sim_console_send_endpoint():
    """Manually send a command (for debugging when no real Minecraft console).

    The dashboard process is separate from the bot process — we don't
    import bot modules here. Instead, we read the connector config
    ourselves and POST directly to the mod if Forge is selected, or
    log a message if RCON is selected (the bot handles that path).
    """
    import traceback
    import requests as _req
    try:
        data = request.get_json() or {}
        cmd = (data.get("command") or "").strip()
        if not cmd:
            return jsonify({"error": "no command"}), 400

        # Live-read the config (don't depend on the bot process)
        cfg_path = paths.config("config.yml")
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        connector = (cfg.get("Settings", {}) or {}).get("ConnectorType", "rcon")
        if connector not in ("rcon", "forge"):
            connector = "rcon"

        # Always append to the local sim console for the UI display
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        log_path = paths.logs("sim_console.log")
        append_sim_console_line(log_path, f"[{ts}] [→] {cmd}")

        if connector == "forge":
            forge = (cfg.get("Forge", {}) or {})
            host = str(forge.get("Host", "127.0.0.1"))
            port = int(forge.get("Port", 5942))
            password = str(forge.get("Password", ""))
            try:
                r = _req.post(
                    f"http://{host}:{port}/command",
                    json={"password": password, "command": cmd},
                    timeout=5,
                )
                if r.status_code == 200:
                    try:
                        out = r.json().get("output", "")
                    except Exception:
                        out = ""
                    append_sim_console_line(
                        log_path,
                        f"[{datetime.datetime.now().strftime('%H:%M:%S')}] " + (out or "[ok]"),
                    )
                    return jsonify({"ok": True, "output": out})
                else:
                    append_sim_console_line(
                        log_path,
                        f"[{datetime.datetime.now().strftime('%H:%M:%S')}] [ERR] HTTP {r.status_code}: {r.text[:200]}",
                    )
                    return jsonify({
                        "ok": False,
                        "error": f"HTTP {r.status_code}: {r.text[:200]}"
                    }), 502
            except _req.exceptions.ConnectionError:
                return jsonify({
                    "ok": False,
                    "error": f"forge mod unreachable at {host}:{port} (is MC running with the mod?)"
                }), 503
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500
        else:
            # RCON path — the bot handles this. We just log that we tried.
            return jsonify({
                "ok": True,
                "note": "RCON mode — bot will execute this on the next event (sim console doesn't drive RCON directly)"
            })
    except Exception as e:
        return jsonify({
            "error": str(e),
            "type": type(e).__name__,
            "trace": traceback.format_exc().splitlines()[-5:]
        }), 500

def get_active_streaks():
    data = safe_json_read(paths.data("active_streaks.json"))
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
    sounds_dir = paths.assets("sounds")
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
    sounds_dir = paths.assets("sounds")
    real_path = os.path.realpath(filepath)
    real_sounds = os.path.realpath(sounds_dir)
    if not real_path.startswith(real_sounds):
        return jsonify({"error": "Access denied"}), 403

    return send_file(filepath, mimetype="audio/mpeg")

@app.route("/overlay-demo/<overlay_type>")
def overlay_demo_page(overlay_type):
    """Demo overlay with dark background for preview."""
    valid_types = ['chat', 'gifts', 'follows', 'superfan', 'topgift', 'topstreak', 'topshowcase', 'topgifter', 'song', 'coingoal', 'giftgoal', 'oneblock', 'roulette']
    if overlay_type not in valid_types:
        return "Invalid overlay type", 404
    return render_template("overlay_demo.html", overlay_type=overlay_type)


@app.route("/overlay/<overlay_type>")
def overlay_page(overlay_type):
    """Serve overlay pages for OBS browser sources."""
    valid_types = ['chat', 'gifts', 'follows', 'superfan', 'topgift', 'topstreak', 'topshowcase', 'topgifter', 'song', 'coingoal', 'giftgoal', 'oneblock', 'roulette']
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
_tts_warmup_started = False
_tts_warmup_lock = threading.Lock()


def _run_async(coro):
    """Run a coroutine in the shared TTS event loop."""
    import concurrent.futures
    future = _asyncio.run_coroutine_threadsafe(coro, _tts_loop)
    return future.result(timeout=30)


def _submit_async(coro):
    """Fire-and-forget submit to the shared background event loop.

    Unlike _run_async this does NOT block the Flask request until the coroutine
    finishes — used by the Roulette test spin, which must return 202 immediately
    while the landing happens up to spin_ms later.
    """
    return _asyncio.run_coroutine_threadsafe(coro, _tts_loop)


TTS_CONFIG_FILE = paths.data("tts_config.json")
TTS_HISTORY_FILE = paths.data("tts_history.json")

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

def _normalize_tts_username(value):
    """Normalize TikTok usernames for TTS permission checks."""
    return str(value or "").strip().lower().lstrip("@")


def _normalize_tts_whitelist(cfg):
    """Normalize saved TTS whitelist entries in-place."""
    perm = cfg.setdefault("permission", {})
    entries = perm.get("whitelist", []) or []
    seen = set()
    normalized = []
    for entry in entries:
        username = _normalize_tts_username(entry)
        if username and username not in seen:
            seen.add(username)
            normalized.append(username)
    perm["whitelist"] = normalized
    return cfg


def _save_tts_config(cfg):
    """Save TTS config."""
    save_json(TTS_CONFIG_FILE, _normalize_tts_whitelist(cfg))


def start_tts_warmup_once():
    """Warm TTS exactly once per process, in the background.

    This pays the edge-tts import/network setup + pygame mixer init before the
    first live viewer TTS. It never plays audio, never writes history, and never
    touches cooldown state.
    """
    global _tts_warmup_started
    with _tts_warmup_lock:
        if _tts_warmup_started:
            return False
        _tts_warmup_started = True

    def _warm():
        log_file = paths.logs("tts_debug.log")
        out_file = None
        try:
            cfg = _load_tts_config()
            if not cfg.get("enabled", True):
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write("[TTS WARMUP] skipped (disabled)\n")
                return

            import edge_tts
            tts_dir = paths.assets("tts")
            os.makedirs(tts_dir, exist_ok=True)
            out_file = os.path.join(tts_dir, "tts_warmup.mp3")

            voice = cfg.get("voice", "en-US-AriaNeural")
            speed = cfg.get("speed", "+0%")
            pitch = cfg.get("pitch", "+0Hz")
            rate = speed if speed and (speed.startswith("+") or speed.startswith("-")) else ("+" + speed)

            async def _gen():
                # Punctuation-only text makes edge-tts raise NoAudioReceived, so
                # the old warmup never primed its network/TLS path. Generate a
                # tiny real clip and discard it without playback instead.
                communicate = edge_tts.Communicate("Ready", voice, rate=rate, pitch=pitch)
                await communicate.save(out_file)

            _run_async(_gen())

            try:
                import pygame
                if not pygame.mixer.get_init():
                    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            except Exception as audio_err:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(f"[TTS WARMUP] mixer init skipped/failed: {audio_err}\n")

            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[TTS WARMUP] ok voice={voice} rate={rate} pitch={pitch}\n")
        except Exception as e:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[TTS WARMUP] failed: {e}\n")
        finally:
            if out_file:
                try:
                    os.remove(out_file)
                except Exception:
                    pass

    threading.Thread(target=_warm, daemon=True).start()
    return True


def _check_tts_permission(cfg, user_info):
    """Check if a user has TTS permission. Returns (allowed, reason)."""
    perm = cfg.get("permission", {})
    uid = _normalize_tts_username(user_info.get("unique_id"))

    # Whitelist always wins
    whitelist = [_normalize_tts_username(w) for w in perm.get("whitelist", [])]
    if uid and uid in whitelist:
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
        log_file = paths.logs("tts_debug.log")
        out_file = None
        processed_file = None
        try:
            import edge_tts, traceback

            tts_dir = paths.assets("tts")
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


# ── COIN GOAL JAR ─────────────────────────────────────────────────
COIN_GOAL_FILE = paths.data("coin_goal.json")
COIN_GOAL_DEFAULTS = {"current": 0, "goal": 10000, "label": "Tip Jar", "sublabel": ""}

# ── TOP GIFT LAYOUT ────────────────────────────────────────
TOP_GIFT_LAYOUT_FILE = paths.data("topgift_layout.json")
TOP_GIFT_LAYOUT_DEFAULTS = {"layout": "left", "updated_at": ""}


@app.route("/api/coingoal", methods=["POST"])
def update_coin_goal():
    """Update coin goal jar state. Called from dashboard Customize popup."""
    data = request.json or {}
    current = load_json(COIN_GOAL_FILE, dict(COIN_GOAL_DEFAULTS))
    if not isinstance(current, dict):
        current = {}
    merged = dict(COIN_GOAL_DEFAULTS)
    merged.update({k: v for k, v in current.items() if k in COIN_GOAL_DEFAULTS})

    mode = data.get("mode", "set")
    if data.get("reset"):
        merged["current"] = 0
    elif mode == "adjust":
        try:
            merged["current"] = max(0, int(merged.get("current", 0)) + int(data.get("current", 0)))
        except (ValueError, TypeError):
            pass
    elif mode == "set":
        if "current" in data:
            try:
                merged["current"] = max(0, int(data["current"]))
            except (ValueError, TypeError):
                pass
        if "goal" in data:
            try:
                merged["goal"] = max(1, int(data["goal"]))
            except (ValueError, TypeError):
                pass
        if "label" in data:
            merged["label"] = str(data["label"]).strip() or merged["label"]
        if "sublabel" in data:
            merged["sublabel"] = str(data["sublabel"]).strip()

    save_json(COIN_GOAL_FILE, merged)
    return jsonify({"status": "success", "data": merged})


# ── GIFT GOAL ─────────────────────────────────────────────────
GIFT_GOAL_FILE = paths.data("gift_goal.json")
GIFT_GOAL_DEFAULTS = {
    "gift_id": "",
    "gift_name": "",
    "gift_icon": "",
    "gift_asset_url": "",
    "gift_diamond_count": 0,
    "gift_primary_effect_id": "",
    "gift_resource_id": "",
    "gift_has_animation": False,
    "goal": 100,
    "current": 0,
    "header": "Goal Today",
}


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


@app.route("/api/giftgoal", methods=["POST"])
def update_gift_goal():
    """Update gift goal state. Called from dashboard Customize popup."""
    data = request.json or {}
    current = load_json(GIFT_GOAL_FILE, dict(GIFT_GOAL_DEFAULTS))
    if not isinstance(current, dict):
        current = {}
    merged = dict(GIFT_GOAL_DEFAULTS)
    merged.update({k: v for k, v in current.items() if k in GIFT_GOAL_DEFAULTS})

    if "reset" in data and data["reset"]:
        merged["current"] = 0
    else:
        if "gift_id" in data:
            merged["gift_id"] = str(data["gift_id"])
        if "gift_name" in data:
            merged["gift_name"] = str(data["gift_name"])
        if "gift_icon" in data:
            merged["gift_icon"] = str(data["gift_icon"])
        if "gift_asset_url" in data:
            merged["gift_asset_url"] = str(data["gift_asset_url"])
        if "gift_diamond_count" in data:
            try:
                merged["gift_diamond_count"] = max(0, int(data["gift_diamond_count"]))
            except (ValueError, TypeError):
                pass
        if "gift_primary_effect_id" in data:
            merged["gift_primary_effect_id"] = str(data["gift_primary_effect_id"])
        if "gift_resource_id" in data:
            merged["gift_resource_id"] = str(data["gift_resource_id"])
        if "gift_has_animation" in data:
            merged["gift_has_animation"] = bool(data["gift_has_animation"])
        if "gift_id" in data and not data.get("gift_asset_url"):
            # Avoid stale animation when switching selected gift. If this gift has
            # already been cached by the top-gift downloader, use it immediately;
            # otherwise the overlay falls back to the static icon.
            merged["gift_asset_url"] = _cached_gift_asset_url(merged.get("gift_id", ""))
        if "goal" in data:
            try:
                merged["goal"] = max(1, int(data["goal"]))
            except (ValueError, TypeError):
                pass
        if "header" in data:
            merged["header"] = str(data["header"]).strip() or merged["header"]
        if "current" in data:
            try:
                merged["current"] = max(0, int(data["current"]))
            except (ValueError, TypeError):
                pass

    save_json(GIFT_GOAL_FILE, merged)
    return jsonify({"status": "success", "data": merged})


# ── TOP GIFT LAYOUT ────────────────────────────────────────
@app.route("/api/topgift/layout", methods=["POST"])
def update_topgift_layout():
    """Update top gift layout choice. Called from dashboard Customize popup."""
    data = request.json or {}
    current = load_json(TOP_GIFT_LAYOUT_FILE, dict(TOP_GIFT_LAYOUT_DEFAULTS))
    if not isinstance(current, dict):
        current = {}
    merged = dict(TOP_GIFT_LAYOUT_DEFAULTS)
    merged.update({k: v for k, v in current.items() if k in TOP_GIFT_LAYOUT_DEFAULTS})
    
    layout = str(data.get("layout", "left")).strip().lower()
    valid_layouts = {"left", "center", "right"}
    if layout not in valid_layouts:
        layout = "left"
    merged["layout"] = layout
    merged["updated_at"] = "2026-08-19T20:00:00Z"  # Would use datetime.utcnow().isoformat() but keeping simple
    
    save_json(TOP_GIFT_LAYOUT_FILE, merged)
    return jsonify({"status": "success", "data": merged})




if __name__ == "__main__":
    ensure_profiles_setup()
    # Start song queue worker for Spotify auto-play
    try:
        from spotify_handler import start_song_queue_worker
        start_song_queue_worker()
    except Exception as e:
        print(f"[SONG-QUEUE] Failed to start worker: {e}")
    try:
        start_tts_warmup_once()
    except Exception as e:
        print(f"[TTS WARMUP] Failed to start: {e}")
    app.run(host="0.0.0.0", port=5000, debug=True)
