"""PNG and GIF export for Gift Card Studio.

Imported only when an export runs — the plan forbids the image stack from
loading in the idle dashboard, so Pillow and the rasterizer are imported inside
functions here rather than at module scope.

Export modes:

* ``card``   — one card at its logical size
* ``page``   — one page at canvas size
* ``pages``  — every page as numbered files
* ``sheet``  — every card on one contact sheet using the current grid
* ``gif``    — the animated timeline (pages + transitions, or a scroll capture)

Transparency is preserved throughout: cards are RGBA and a transparent canvas
stays transparent, because these are OBS overlay assets, not screenshots.
"""
from __future__ import annotations

import os

from . import frame, grid, models, playback, renderer

# Guard rails so a mis-typed export cannot allocate gigabytes mid-stream.
MAX_EXPORT_PIXELS = 8192 * 8192
MAX_GIF_FRAMES = 900          # 60s at 15fps
MAX_GIF_PIXELS = 2048 * 2048  # per frame

VALID_FPS = (10, 15, 20, 30)
DEFAULT_FPS = 15

GIF_TRANSPARENT_INDEX = 255

# GIF stores frame delays in centiseconds, so an arbitrary ms/frame cannot be
# represented exactly: 15fps is 66.67ms, and naively rounding every frame to
# 60ms makes the whole animation play ~11% fast and a 2000ms loop encode as
# 1940ms. Durations are therefore allocated with an accumulator (below) so the
# cumulative timeline stays correct even though individual frames wobble by 10ms.
GIF_CENTISECOND = 10

# Alpha -> mask lookup: anything at or below 50% opacity becomes transparent.
# GIF has only one-bit transparency, so a cutoff is unavoidable; 127 keeps
# antialiased card edges opaque instead of eating them.
_ALPHA_CUTOFF_TABLE = [255 if value <= 127 else 0 for value in range(256)]


def gif_frame_durations(frame_times, total_ms) -> list[int]:
    """Per-frame GIF delays in ms, each a multiple of 10, summing to ``total_ms``.

    Walks the ideal frame boundaries and rounds each *cumulative* time to the
    nearest centisecond, taking the difference. Rounding error never
    accumulates, so a 30-frame 2000ms loop encodes as exactly 2000ms.
    """
    if not frame_times:
        return []

    boundaries = list(frame_times[1:]) + [int(total_ms)]
    durations = []
    emitted = 0
    for boundary in boundaries:
        target = int(round(float(boundary) / GIF_CENTISECOND) * GIF_CENTISECOND)
        delay = max(GIF_CENTISECOND, target - emitted)
        durations.append(delay)
        emitted += delay
    return durations


class ExportError(RuntimeError):
    """Raised when an export cannot be produced."""


class ExportCancelled(RuntimeError):
    """Raised when a caller's cancel check fires mid-export."""


def _check_cancel(is_cancelled):
    if is_cancelled is not None and is_cancelled():
        raise ExportCancelled("export cancelled")


def _scaled_dimensions(width, height, scale=1.0, target_width=None, target_height=None):
    """Resolve output pixel dimensions from a scale or explicit target size."""
    width = max(1, int(round(float(width))))
    height = max(1, int(round(float(height))))

    if target_width or target_height:
        if target_width and target_height:
            out_w = int(target_width)
            out_h = int(target_height)
        elif target_width:
            out_w = int(target_width)
            out_h = max(1, int(round(height * (out_w / width))))
        else:
            out_h = int(target_height or 0)
            out_w = max(1, int(round(width * (out_h / height))))
    else:
        factor = max(0.01, float(scale or 1.0))
        out_w = max(1, int(round(width * factor)))
        out_h = max(1, int(round(height * factor)))

    if out_w * out_h > MAX_EXPORT_PIXELS:
        raise ExportError(
            f"requested export is too large: {out_w}x{out_h} exceeds the pixel budget"
        )
    return out_w, out_h


def estimate_export(project: dict, mode="page", fps=DEFAULT_FPS, scale=1.0,
                    duration_ms=None) -> dict:
    """Pre-export estimate: dimensions, file/frame count, duration, rough bytes.

    Shown before the user commits, so a 30fps 1920x1080 GIF is a visible
    decision rather than a surprise stall.
    """
    project = models.normalize_project(project)
    canvas = project["canvas"]
    width, height = _scaled_dimensions(canvas["width"], canvas["height"], scale)
    pages = project["pages"]

    if mode == "gif":
        frames = playback.frame_count(project, fps, duration_ms)
        total_ms = int(duration_ms if duration_ms is not None else playback.loop_duration_ms(project))
        # GIF is palettized: ~1 byte/px worst case before LZW, which typically
        # halves it. Deliberately pessimistic so the warning fires early.
        rough_bytes = frames * width * height // 2
        return {
            "mode": mode, "width": width, "height": height,
            "frame_count": frames, "duration_ms": total_ms, "fps": int(fps),
            "file_count": 1, "estimated_bytes": rough_bytes,
            "exceeds_frame_limit": frames > MAX_GIF_FRAMES,
            "exceeds_pixel_limit": width * height > MAX_GIF_PIXELS,
        }

    if mode == "pages":
        file_count = len(pages)
    elif mode == "card":
        file_count = 1
    elif mode == "sheet":
        file_count = 1
    else:
        file_count = 1

    return {
        "mode": mode, "width": width, "height": height,
        "frame_count": file_count, "duration_ms": 0, "fps": 0,
        "file_count": file_count,
        # PNG RGBA before compression.
        "estimated_bytes": file_count * width * height * 4 // 3,
        "exceeds_frame_limit": False,
        "exceeds_pixel_limit": width * height > MAX_EXPORT_PIXELS,
    }


# ---- PNG -----------------------------------------------------------------

def _prepare_svg(svg: str, base_dir=None, data_dir=None, inline_assets=True):
    """Inline every asset reference so the rasterizer can see real bytes.

    Without this an exported card renders its gift icon as nothing: the
    rasterizer has no HTTP client and no idea what ``/gift_assets/x.png`` means.
    """
    if not inline_assets:
        return svg, {"total": 0, "inlined": 0, "dropped": 0, "missing": []}

    import paths as app_paths
    from . import assets as asset_resolver

    root = base_dir or app_paths.BASE_DIR
    data_root = data_dir or app_paths.DATA_DIR
    manifest = {}
    try:
        from .catalog import load_icon_manifest
        manifest = load_icon_manifest(os.path.join(root, "assets"))
    except Exception:
        manifest = {}

    return asset_resolver.inline_svg_assets(svg, root, data_root, manifest)


def render_card_png(card: dict, scale=1.0, background=None, base_dir=None,
                    data_dir=None, inline_assets=True) -> bytes:
    """One card as transparent PNG bytes."""
    from .rasterizer import svg_to_png_bytes

    card = models.normalize_card(card)
    svg, _ = _prepare_svg(
        renderer.render_card_svg(card), base_dir, data_dir, inline_assets
    )
    width, height = _scaled_dimensions(card["width"], card["height"], scale)
    return svg_to_png_bytes(svg, width, height, background, base_dir)


def render_page_png(page: dict, canvas: dict, scale=1.0, background=None,
                    base_dir=None, data_dir=None, inline_assets=True) -> bytes:
    """One page as PNG bytes at canvas size (times ``scale``)."""
    from .rasterizer import svg_to_png_bytes

    svg, _ = _prepare_svg(
        renderer.render_page_svg(page, canvas), base_dir, data_dir, inline_assets
    )
    width, height = _scaled_dimensions(canvas["width"], canvas["height"], scale)
    return svg_to_png_bytes(svg, width, height, background, base_dir)


def render_sheet_png(project: dict, scale=1.0, background=None, base_dir=None,
                     data_dir=None, inline_assets=True) -> bytes:
    """Every card in the project on one contact sheet.

    Reuses the first page's grid so the sheet matches the layout the user has
    been designing against, growing rows as needed rather than dropping cards.
    """
    from .rasterizer import svg_to_png_bytes

    project = models.normalize_project(project)
    cards = [card for page in project["pages"] for card in (page.get("cards") or [])]
    if not cards:
        raise ExportError("project has no cards to export")

    template = project["pages"][0]
    base_grid = dict(template["grid"])
    columns = max(1, int(base_grid.get("columns", 1)))
    rows = max(1, -(-len(cards) // columns))

    canvas = dict(project["canvas"])
    # Grow the sheet vertically so every card gets a real cell.
    cell_h = grid.cell_size(canvas["width"], canvas["height"], template["grid"])[1]
    padding = float(base_grid.get("padding", 0) or 0)
    gap_y = float(base_grid.get("gap_y", 0) or 0)
    canvas["height"] = int(round(rows * cell_h + max(0, rows - 1) * gap_y + 2 * padding))

    base_grid["rows"] = rows
    sheet_page = {"grid": base_grid, "cards": cards, "scroll": template.get("scroll")}

    svg, _ = _prepare_svg(
        renderer.render_page_svg(sheet_page, canvas), base_dir, data_dir, inline_assets
    )
    width, height = _scaled_dimensions(canvas["width"], canvas["height"], scale)
    return svg_to_png_bytes(svg, width, height, background, base_dir)


def _safe_filename(stem, index=None, extension=".png") -> str:
    cleaned = "".join(ch for ch in str(stem or "export") if ch.isalnum() or ch in "-_")
    cleaned = cleaned or "export"
    if index is None:
        return f"{cleaned}{extension}"
    return f"{cleaned}-{index:03d}{extension}"


def _write_bytes(path, data, written) -> None:
    """Render-then-write, tracking the path for rollback.

    The render must complete *before* the file is created: opening first leaves
    a zero-byte file on disk if rendering raises, and that orphan is invisible
    to the rollback list. Tracked immediately after creation so any later
    failure in the batch removes it.
    """
    with open(path, "wb") as handle:
        written.append(path)
        handle.write(data)


def export_png(project: dict, output_dir: str, mode="page", page_index=0,
               card_id=None, scale=1.0, background=None, base_dir=None,
               is_cancelled=None) -> dict:
    """Write PNG file(s) and return a report.

    On cancellation or failure every file written by this call is removed, so a
    broken export never leaves a half-written set behind.
    """
    project = models.normalize_project(project)
    pages = project["pages"]
    os.makedirs(output_dir, exist_ok=True)
    written: list[str] = []

    try:
        if mode == "card":
            card = next((candidate for candidate in project['card_library']
                         if card_id is None or candidate.get('id') == card_id), None)
            if card is None:
                raise ExportError("card not found")
            _check_cancel(is_cancelled)
            data = render_card_png(card, scale, background, base_dir)
            path = os.path.join(output_dir, _safe_filename(card.get("name") or "card"))
            _write_bytes(path, data, written)

        elif mode == "cards":
            cards = project['card_library']
            if not cards:
                raise ExportError("project has no cards to export")
            for index, card in enumerate(cards, start=1):
                _check_cancel(is_cancelled)
                data = render_card_png(card, scale, background, base_dir)
                path = os.path.join(
                    output_dir, _safe_filename(card.get("name") or "card", index)
                )
                _write_bytes(path, data, written)

        elif mode == "pages":
            for index, page in enumerate(pages, start=1):
                _check_cancel(is_cancelled)
                data = render_page_png(page, project["canvas"], scale, background, base_dir)
                path = os.path.join(output_dir, _safe_filename(project["id"], index))
                _write_bytes(path, data, written)

        elif mode == "sheet":
            _check_cancel(is_cancelled)
            data = render_sheet_png(project, scale, background, base_dir)
            path = os.path.join(output_dir, _safe_filename(project["id"] + "-sheet"))
            _write_bytes(path, data, written)

        else:  # single page
            if not 0 <= int(page_index) < len(pages):
                raise ExportError(f"page index out of range: {page_index}")
            _check_cancel(is_cancelled)
            data = render_page_png(
                pages[int(page_index)], project["canvas"], scale, background, base_dir
            )
            path = os.path.join(output_dir, _safe_filename(project["id"]))
            _write_bytes(path, data, written)

    except BaseException:
        for path in written:
            try:
                os.remove(path)
            except OSError:
                pass
        raise

    return {"mode": mode, "files": written, "file_count": len(written)}


# ---- GIF -----------------------------------------------------------------

def _lerp(a, b, t):
    return a + (b - a) * float(t)


def render_frame_svg(project: dict, time_ms) -> str:
    """SVG for one timeline frame, including any in-flight transition.

    Thin wrapper over ``frame.frame_svg``. Frame composition lives in its own
    module so the OBS overlay renders transitions from the same definition (via
    its JS mirror) instead of the exporter owning them privately.
    """
    return frame.frame_svg(project, time_ms)


def render_gif_frames(project: dict, fps=DEFAULT_FPS, duration_ms=None, scale=1.0,
                      background=None, base_dir=None, is_cancelled=None,
                      on_progress=None):
    """Yield one RGBA PIL image per frame. Generator: frames are not all held.

    Holding 270 full-size RGBA frames at once is hundreds of MB — unacceptable
    on a streaming PC — so this yields lazily and the encoder consumes as it goes.
    """
    from .rasterizer import svg_to_image

    project = models.normalize_project(project)
    canvas = project["canvas"]
    width, height = _scaled_dimensions(canvas["width"], canvas["height"], scale)

    if width * height > MAX_GIF_PIXELS:
        raise ExportError(
            f"GIF frame size {width}x{height} exceeds the per-frame pixel limit"
        )

    times = playback.frame_times(project, fps, duration_ms)
    if len(times) > MAX_GIF_FRAMES:
        raise ExportError(
            f"GIF would need {len(times)} frames, over the {MAX_GIF_FRAMES} limit; "
            "lower the FPS or shorten the duration"
        )

    for index, time_ms in enumerate(times):
        _check_cancel(is_cancelled)
        svg, _ = _prepare_svg(
            render_frame_svg(project, time_ms), base_dir, None, True
        )
        image = svg_to_image(svg, width, height, background, base_dir)
        if on_progress is not None:
            on_progress(index + 1, len(times))
        yield image


def export_gif(project: dict, output_path: str, fps=DEFAULT_FPS, duration_ms=None,
               scale=1.0, loop=0, background=None, base_dir=None,
               is_cancelled=None, on_progress=None) -> dict:
    """Encode the timeline to an animated GIF.

    Transparency note (surfaced to the user by the UI): GIF supports only
    one-bit transparency and 256 colours, so soft edges harden. The OBS browser
    output or a PNG sequence keeps full alpha.
    """
    project = models.normalize_project(project)
    if int(fps) not in VALID_FPS:
        raise ExportError(f"unsupported fps: {fps}; choose one of {VALID_FPS}")

    times = playback.frame_times(project, fps, duration_ms)
    total_ms = int(duration_ms if duration_ms is not None else playback.loop_duration_ms(project))
    durations = gif_frame_durations(times, total_ms)
    frames = []
    written = False

    try:
        for image in render_gif_frames(
            project, fps, duration_ms, scale, background, base_dir,
            is_cancelled, on_progress,
        ):
            # Quantize per frame with a transparent palette slot reserved.
            alpha = image.getchannel("A")
            quantized = image.convert("RGB").quantize(colors=255)
            # Pixels below 50% alpha become the transparent index. A lookup
            # table is both faster than a lambda and unambiguous to type.
            mask = alpha.point(_ALPHA_CUTOFF_TABLE)
            quantized.paste(GIF_TRANSPARENT_INDEX, mask)
            frames.append(quantized)

        if not frames:
            raise ExportError("no frames were produced")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
        frames[0].save(
            output_path,
            save_all=True,
            append_images=frames[1:],
            duration=durations[: len(frames)],
            loop=int(loop),
            disposal=2,
            transparency=GIF_TRANSPARENT_INDEX,
            # Pillow's GIF optimizer merges visually similar frames, which
            # silently drops frames and lengthens the survivors' delays. That
            # breaks the deterministic frame count the timeline promises.
            optimize=False,
        )
        written = True
    except BaseException:
        if written or os.path.exists(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
        raise
    finally:
        # Release the palettized frames promptly rather than waiting for GC.
        for frame in frames:
            try:
                frame.close()
            except Exception:
                pass
        frames.clear()

    # Pillow's GIF writer collapses a frame that is byte-identical to its
    # predecessor into that frame with a longer delay. For a static page held
    # for a second, that is correct and much smaller — the *timeline* is
    # unchanged because the merged delay equals the frames it replaced. Report
    # both numbers so the UI never claims frames the file does not contain.
    encoded = _count_gif_frames(output_path)

    return {
        "path": output_path,
        "frame_count": len(times),
        "encoded_frame_count": encoded,
        "fps": int(fps),
        "duration_ms": sum(durations),
        "loop": int(loop),
        "bytes": os.path.getsize(output_path),
    }


def _count_gif_frames(path) -> int:
    """Frames actually present in the encoded file."""
    from PIL import Image

    try:
        with Image.open(path) as image:
            return int(getattr(image, "n_frames", 1))
    except Exception:
        return 0
