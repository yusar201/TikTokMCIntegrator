"""Generate-then-download flow: turn export settings into one downloadable file.

The Studio is a **generator**, not a live overlay source. Khito designs a
project, presses Generate, and gets a single file to drop into OBS as an image
source. That shapes two decisions here:

* **One file per generate.** ``export_png`` can emit a whole directory (every
  card, every page), but "drop it into OBS" means one artifact. Multi-file modes
  are therefore zipped, and single-file modes are handed over untouched — no
  pointless archive around a lone PNG.
* **Settings are validated before any rasterization starts.** A rejected fps or
  an oversized canvas should fail instantly, not 200 frames in.

Everything runs inside a ``jobs`` worker, so a 300-frame GIF never blocks a
request or competes with gift dispatch on a live stream.
"""
from __future__ import annotations

import os
import zipfile

from . import exporter, models, playback, storage

# Formats the Generate button offers.
FORMAT_PNG = "png"
FORMAT_GIF = "gif"
VALID_FORMATS = (FORMAT_PNG, FORMAT_GIF)

# PNG composition modes, in the order the UI lists them.
PNG_MODES = ("page", "pages", "card", "cards", "sheet")

# Modes that produce more than one file and therefore get zipped.
MULTI_FILE_MODES = ("pages", "cards")

# Upper bound on scale. Beyond this the pixel guard in the exporter would reject
# it anyway; catching it here gives a clearer message.
MAX_SCALE = 8.0

# A GIF longer than this is almost never what someone wants as an OBS source and
# costs minutes to generate.
MAX_GIF_DURATION_MS = 60_000


class SettingsError(ValueError):
    """Invalid generate settings. Reported to the user verbatim."""


def _as_float(value, default, name):
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        raise SettingsError(f"{name} must be a number") from None


def _as_int(value, default, name):
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        raise SettingsError(f"{name} must be a whole number") from None


def normalize_settings(raw: dict | None) -> dict:
    """Validate and fill in Generate settings.

    Raises ``SettingsError`` with a message aimed at the person who set the
    control, not at a developer reading a traceback.
    """
    raw = raw or {}

    export_format = str(raw.get("format") or FORMAT_PNG).lower().strip()
    if export_format not in VALID_FORMATS:
        raise SettingsError(
            f"format must be one of {', '.join(VALID_FORMATS)} (got '{export_format}')"
        )

    scale = _as_float(raw.get("scale"), 1.0, "scale")
    if not 0 < scale <= MAX_SCALE:
        raise SettingsError(f"scale must be greater than 0 and at most {MAX_SCALE:g}")

    background = raw.get("background")
    if background in ("", "transparent", None):
        background = None
    elif not isinstance(background, str):
        raise SettingsError("background must be a colour string or omitted")

    settings = {
        "format": export_format,
        "scale": scale,
        "background": background,
    }

    if export_format == FORMAT_PNG:
        mode = str(raw.get("mode") or "page").lower().strip()
        if mode not in PNG_MODES:
            raise SettingsError(f"mode must be one of {', '.join(PNG_MODES)} (got '{mode}')")
        settings["mode"] = mode
        settings["page_index"] = _as_int(raw.get("page_index"), 0, "page_index")
        if settings["page_index"] < 0:
            raise SettingsError("page_index cannot be negative")
        card_id = raw.get("card_id")
        settings["card_id"] = str(card_id) if card_id else None
        return settings

    fps = _as_int(raw.get("fps"), exporter.DEFAULT_FPS, "fps")
    if fps not in exporter.VALID_FPS:
        raise SettingsError(
            f"fps must be one of {', '.join(str(v) for v in exporter.VALID_FPS)} (got {fps})"
        )
    settings["fps"] = fps

    duration = raw.get("duration_ms")
    if duration in (None, "", 0, "0"):
        settings["duration_ms"] = None
    else:
        duration_ms = _as_int(duration, 0, "duration_ms")
        if duration_ms <= 0:
            raise SettingsError("duration_ms must be positive, or omitted to use one loop")
        if duration_ms > MAX_GIF_DURATION_MS:
            raise SettingsError(
                f"duration_ms cannot exceed {MAX_GIF_DURATION_MS // 1000}s"
            )
        settings["duration_ms"] = duration_ms

    # loop=0 means forever in the GIF spec; anything else is a repeat count.
    settings["loop"] = max(0, _as_int(raw.get("loop"), 0, "loop"))
    return settings


def estimate(project: dict, settings: dict) -> dict:
    """What a generate *would* produce, without rendering anything.

    Lets the UI warn about a 300-frame job before the user commits to it, and
    lets the API reject an impossible request up front.
    """
    project = models.normalize_project(project)
    canvas = project["canvas"]
    scale = settings["scale"]
    out_w = int(canvas["width"] * scale)
    out_h = int(canvas["height"] * scale)
    pages = project["pages"]
    card_count = len(project['card_library'])

    info = {
        "format": settings["format"],
        "output_width": out_w,
        "output_height": out_h,
        "pixels": out_w * out_h,
        "card_count": card_count,
        "page_count": len(pages),
    }

    if settings["format"] == FORMAT_PNG:
        mode = settings["mode"]
        if mode == "pages":
            info["file_count"] = len(pages)
        elif mode == "cards":
            info["file_count"] = card_count
        else:
            info["file_count"] = 1
        info["zipped"] = mode in MULTI_FILE_MODES and info["file_count"] > 1
        info["frame_count"] = 0
        return info

    duration_ms = settings["duration_ms"]
    total_ms = int(
        duration_ms if duration_ms is not None else playback.loop_duration_ms(project)
    )
    frames = len(playback.frame_times(project, settings["fps"], duration_ms))
    info.update({
        "file_count": 1,
        "zipped": False,
        "frame_count": frames,
        "duration_ms": total_ms,
        "fps": settings["fps"],
    })
    return info


def check_feasible(project: dict, settings: dict) -> dict:
    """Raise ``SettingsError`` if this generate cannot succeed. Returns estimate."""
    info = estimate(project, settings)

    if info["pixels"] > exporter.MAX_EXPORT_PIXELS:
        raise SettingsError(
            f"output is {info['output_width']}x{info['output_height']} "
            f"({info['pixels'] / 1e6:.1f} megapixels); reduce the canvas or scale"
        )

    if settings["format"] == FORMAT_GIF:
        if info["frame_count"] > exporter.MAX_GIF_FRAMES:
            raise SettingsError(
                f"{info['frame_count']} frames exceeds the {exporter.MAX_GIF_FRAMES}-frame "
                f"limit; shorten the animation or lower the fps"
            )
        if info["pixels"] > exporter.MAX_GIF_PIXELS:
            raise SettingsError(
                f"GIF frames are capped at {exporter.MAX_GIF_PIXELS / 1e6:.0f} megapixels; "
                f"this canvas is {info['pixels'] / 1e6:.1f}"
            )
        if info["frame_count"] <= 0:
            raise SettingsError("this project has no animation to generate")

    if settings["format"] == FORMAT_PNG:
        mode = settings["mode"]
        if mode in ("card", "cards") and info["card_count"] == 0:
            raise SettingsError("this project has no cards to generate")
        if mode == "page" and settings["page_index"] >= info["page_count"]:
            raise SettingsError(
                f"page {settings['page_index'] + 1} does not exist "
                f"(project has {info['page_count']})"
            )

    return info


def _zip_files(paths, archive_path) -> str:
    """Bundle multiple PNGs into one download."""
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, arcname=os.path.basename(path))
    # The individual PNGs served their purpose; only the archive is downloaded.
    for path in paths:
        try:
            os.remove(path)
        except OSError:
            pass
    return archive_path


def _slug(project: dict) -> str:
    raw = str(project.get("id") or project.get("name") or "overlay")
    keep = [c if (c.isalnum() or c in "-_") else "-" for c in raw.lower()]
    slug = "".join(keep).strip("-") or "overlay"
    return slug[:48]


def generate(project: dict, settings: dict, context, base_dir=None):
    """Produce exactly one downloadable artifact. Runs inside a job worker.

    Returns ``(artifact_path, report)``.
    """
    project = models.normalize_project(project)
    info = check_feasible(project, settings)
    slug = _slug(project)

    if settings["format"] == FORMAT_GIF:
        total = max(1, info["frame_count"])
        context.progress(0, total)

        def on_progress(done, count):
            context.progress(done, count or total)

        output = os.path.join(context.output_dir, f"{slug}.gif")
        report = exporter.export_gif(
            project,
            output,
            fps=settings["fps"],
            duration_ms=settings["duration_ms"],
            scale=settings["scale"],
            loop=settings["loop"],
            background=settings["background"],
            base_dir=base_dir,
            is_cancelled=context.cancelled,
            on_progress=on_progress,
        )
        context.progress(total, total)
        report["estimate"] = info
        return output, report

    # PNG. Progress is per file; a single-file mode jumps 0 -> 1.
    total = max(1, info["file_count"])
    context.progress(0, total)
    report = exporter.export_png(
        project,
        context.output_dir,
        mode=settings["mode"],
        page_index=settings["page_index"],
        card_id=settings["card_id"],
        scale=settings["scale"],
        background=settings["background"],
        base_dir=base_dir,
        is_cancelled=context.cancelled,
    )
    context.progress(total, total)

    files = report["files"]
    if not files:
        raise SettingsError("nothing was generated")

    if len(files) == 1:
        # One PNG: hand it over directly. Wrapping it in a zip would only make
        # the user unpack it before using it.
        report["estimate"] = info
        report["zipped"] = False
        return files[0], report

    archive = os.path.join(context.output_dir, f"{slug}-{settings['mode']}.zip")
    _zip_files(files, archive)
    report["estimate"] = info
    report["zipped"] = True
    report["archived_file_count"] = len(files)
    return archive, report


def submit_generate(project: dict, settings: dict, data_dir=None, base_dir=None,
                    deliver_to=None) -> dict:
    """Validate, then start a generation job. Raises before spawning on bad input.

    ``deliver_to`` is the folder the finished file is copied into. Pass None to
    keep the artifact download-only (used by tests and by a browser session with
    no folder chosen yet).
    """
    from . import jobs

    settings = normalize_settings(settings)
    # Fail fast, in the request, so the user sees the reason immediately rather
    # than a job that dies a second later.
    check_feasible(project, settings)

    def work(context):
        return generate(project, settings, context, base_dir=base_dir)

    job = jobs.submit(
        settings["format"], str(project.get("id") or ""), work, data_dir,
        deliver_to=deliver_to,
    )
    job["settings"] = settings
    return job
