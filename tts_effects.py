"""
TTS Effects — whisper/yell modes for edge-tts.

Applies SSML prosody for rate/volume/pitch shifts,
and optional ffmpeg post-processing for real audio effects.

Viewer syntax:
  . *whisper* hello everyone   → whisper mode
  . [yell] come here           → yell mode
  . hello                      → normal (default)
"""

import os
import re
import subprocess
import tempfile

# ── Effect Definitions ──────────────────────────────────────────────

EFFECTS = {
    "whisper": {
        "ssml_volume": "soft",
        "ssml_rate": "-15%",
        "ssml_pitch": "-10Hz",
        "ffmpeg_filter": "volume=0.4,highpass=f=300,lowpass=f=3500,aresample=44100",
        "pygame_volume": 0.6,
    },
    "yell": {
        "ssml_volume": "loud",
        "ssml_rate": "+10%",
        "ssml_pitch": "+5Hz",
        "ffmpeg_filter": "volume=2.5,acompressor=threshold=0.02:ratio=6:attack=5:release=50",
        "pygame_volume": 1.0,
    },
    "normal": {
        "ssml_volume": "medium",
        "ssml_rate": "+0%",
        "ssml_pitch": "+0Hz",
        "ffmpeg_filter": None,
        "pygame_volume": 1.0,
    },
}

# ── Pattern matching for effect tags ────────────────────────────────

# Matches: *whisper*, [whisper], {whisper}, (whisper)
_EFFECT_PATTERN = re.compile(
    r"^[\s]*[\*\[\{\(](whisper|yell|shout|scream|quiet|loud|whisp)[\*\]\}\)]\s*",
    re.IGNORECASE,
)

# Alias mapping → canonical effect name
_EFFECT_ALIASES = {
    "whisper": "whisper",
    "whisp": "whisper",
    "quiet": "whisper",
    "yell": "yell",
    "shout": "yell",
    "scream": "yell",
    "loud": "yell",
}


def parse_effect(text: str) -> tuple[str, str]:
    """
    Parse effect tag from viewer text.

    Returns (effect_name, cleaned_text).
    Examples:
        "*whisper* hello"  → ("whisper", "hello")
        "[yell] come here" → ("yell", "come here")
        "hello world"      → ("normal", "hello world")
    """
    match = _EFFECT_PATTERN.match(text)
    if match:
        raw_tag = match.group(1).lower()
        effect = _EFFECT_ALIASES.get(raw_tag, "normal")
        cleaned = text[match.end():].strip()
        if cleaned:
            return effect, cleaned
        # Tag only, no text — treat as normal
        return "normal", text
    return "normal", text


def get_effect_config(effect: str) -> dict:
    """Get effect configuration dict. Falls back to normal."""
    return EFFECTS.get(effect, EFFECTS["normal"])


def wrap_ssml(text: str, effect: str, base_rate: str = "+0%", base_pitch: str = "+0Hz") -> str:
    """
    Wrap text in SSML with prosody tags for the given effect.

    Args:
        text: The text to speak.
        effect: Effect name (whisper, yell, normal).
        base_rate: Base rate from TTS config (e.g. "+0%").
        base_pitch: Base pitch from TTS config (e.g. "+0Hz").

    Returns:
        SSML string ready for edge_tts.Communicate().
    """
    cfg = get_effect_config(effect)

    if effect == "normal":
        # No SSML wrapping needed for normal — let edge_tts handle rate/pitch directly
        return text

    # Build SSML with prosody attributes
    volume = cfg["ssml_volume"]
    rate = cfg["ssml_rate"]
    pitch = cfg["ssml_pitch"]

    # Escape XML special chars in text
    safe_text = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )

    ssml = (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">'
        f'<prosody volume="{volume}" rate="{rate}" pitch="{pitch}">'
        f"{safe_text}"
        f"</prosody></speak>"
    )
    return ssml


def apply_audio_effects(input_path: str, effect: str) -> str:
    """
    Apply ffmpeg post-processing to an audio file for the given effect.

    Args:
        input_path: Path to the input MP3 file.
        effect: Effect name (whisper, yell, normal).

    Returns:
        Path to the processed file (same as input if no ffmpeg or normal effect).
        Caller should NOT delete this file — it's either the original or a temp file.
    """
    cfg = get_effect_config(effect)
    ffmpeg_filter = cfg.get("ffmpeg_filter")

    if not ffmpeg_filter or effect == "normal":
        return input_path

    # Check if ffmpeg is available
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # ffmpeg not available — skip post-processing, SSML-only mode
        return input_path

    # Apply ffmpeg filter
    output_path = input_path.replace(".mp3", f"_{effect}.mp3")
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", input_path,
                "-af", ffmpeg_filter,
                "-ar", "44100",
                "-ac", "1",
                output_path,
            ],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0 and os.path.exists(output_path):
            return output_path
    except Exception:
        pass

    # Fallback: return original
    return input_path
