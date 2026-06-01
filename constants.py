"""
Constants for TikTokMCIntegrator
All magic numbers, timeouts, and configuration values in one place.
"""
import os
import sys

# ── Paths ───────────────────────────────────────────────────────
# Resolve BASE_DIR — works both as .py script and as packaged .exe
# When imported from a frozen app, sys.executable is the exe path
BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) \
           else os.path.dirname(os.path.abspath(__file__))

# ── API Configuration ──────────────────────────────────────────────
API_PORT = 5000
LOCAL_API_URL = f"http://127.0.0.1:{API_PORT}"

# ── Timeouts (seconds) ─────────────────────────────────────────────
BOT_SHUTDOWN_TIMEOUT = 5
HTTP_REQUEST_TIMEOUT = 10
ASYNC_FUTURE_TIMEOUT = 30
RCON_TIMEOUT = 5
TTS_REQUEST_TIMEOUT = 5

# ── Limits ──────────────────────────────────────────────────────────
MAX_TTS_HISTORY = 500
MAX_SONG_HISTORY = 500
MAX_BOT_LOGS = 1000
MAX_TTS_TEXT_LENGTH = 200
MAX_QUEUE_PER_USER = 5
MAX_QUEUE_TOTAL = 20

# ── Cooldowns (seconds) ────────────────────────────────────────────
DEFAULT_GLOBAL_COOLDOWN = 2
DEFAULT_USER_COOLDOWN = 10
DEFAULT_SONG_COOLDOWN = 5

# ── TTS Effects ─────────────────────────────────────────────────────
TTS_EFFECTS = ("normal", "whisper", "yell")

# ── File Names ──────────────────────────────────────────────────────
CONFIG_FILE = "config.yml"
ACTIVE_PROFILE_FILE = "active_profile.txt"
TTS_CONFIG_FILE = "tts_config.json"
TTS_HISTORY_FILE = "tts_history.json"
SONG_CONFIG_FILE = "song_config.json"
SONG_QUEUE_FILE = "song_queue.json"
SONG_HISTORY_FILE = "song_history.json"
SONG_TOKEN_FILE = "song_spotify_token.json"
STREAM_STATE_FILE = "stream_state.json"
CHAT_LOG_FILE = "chat_log.json"
GIFT_LOG_FILE = "gift_log.json"
FOLLOW_LOG_FILE = "follow_log.json"
VIEWER_STATS_FILE = "viewer_stats.json"
