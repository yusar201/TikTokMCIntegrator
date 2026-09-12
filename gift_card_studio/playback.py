"""Deterministic playback timeline for Gift Card Studio.

``state_at(project, ms)`` is a pure function of (project, time) — the same input
always yields the same output. That is what makes GIF export possible: the
exporter walks the timeline at fixed intervals and rasterizes each state, rather
than screen-recording an animation and hoping the frames line up.

Two playback modes:

* **pages** — each page shows for its duration; a transition cross-fades/wipes
  from the previous page over the *leading* edge of the incoming page.
* **scroll** — content translates continuously at an exact px/s, with an
  optional pause at each edge when not looping seamlessly.

Mirrored by ``static/gift-studio/playback.js`` and covered by a parity test, for
the same reason the grid is: the editor preview and the export must agree.

Pure module: stdlib only, no I/O.
"""
from __future__ import annotations

from . import grid, models
from .numeric import js_round

# Below this, a transition is treated as an instant cut — sub-frame fades just
# add work and produce banding.
MIN_MEANINGFUL_TRANSITION_MS = 1


def page_windows(project: dict) -> list[dict]:
    """Absolute time windows for every page in one loop.

    Each entry: ``{index, page_id, start_ms, end_ms, duration_ms,
    transition_type, transition_ms}`` where the transition covers
    ``[start_ms, start_ms + transition_ms)`` of that page.
    """
    playback = project.get("playback") or {}
    pages = project.get("pages") or []
    windows = []
    cursor = 0

    for index, page in enumerate(pages):
        duration = models.page_duration_ms(page, playback)
        previous = pages[index - 1] if index > 0 else (pages[-1] if len(pages) > 1 else None)
        transition = models.page_transition(page, playback)
        transition_ms = models.effective_transition_ms(page, previous, playback)
        if transition_ms < MIN_MEANINGFUL_TRANSITION_MS:
            transition_ms = 0
        windows.append({
            "index": index,
            "page_id": page.get("id"),
            "start_ms": cursor,
            "end_ms": cursor + duration,
            "duration_ms": duration,
            "transition_type": "cut" if transition_ms == 0 else transition.get("type", "cut"),
            "transition_ms": transition_ms,
        })
        cursor += duration

    return windows


def loop_duration_ms(project: dict) -> int:
    """Length of one full loop for the project's playback mode."""
    playback = project.get("playback") or {}
    if playback.get("mode") == "scroll":
        return scroll_loop_duration_ms(project)
    return models.project_duration_ms(project)


# ---- Pages ---------------------------------------------------------------

def _normalize_time(time_ms, total_ms, loop) -> float:
    """Fold a time into ``[0, total_ms)`` when looping, else clamp to the end."""
    if total_ms <= 0:
        return 0.0
    time_ms = float(time_ms)
    if time_ms < 0:
        return 0.0
    if time_ms < total_ms:
        return time_ms
    if loop:
        return time_ms % total_ms
    # Non-looping: hold the final frame rather than going blank.
    return float(total_ms) - 1e-9


def pages_state_at(project: dict, time_ms) -> dict:
    """Which page (and optional incoming/outgoing pair) is visible at ``time_ms``."""
    playback = project.get("playback") or {}
    pages = project.get("pages") or []
    windows = page_windows(project)
    total = windows[-1]["end_ms"] if windows else 0

    if not pages or total <= 0:
        return {
            "mode": "pages", "time_ms": 0.0, "loop_ms": 0,
            "page_index": 0, "page": None,
            "previous_index": None, "previous_page": None,
            "transition_type": "cut", "transition_progress": 1.0,
            "scroll": None,
        }

    local = _normalize_time(time_ms, total, bool(playback.get("loop", True)))

    window = windows[-1]
    for candidate in windows:
        if local < candidate["end_ms"]:
            window = candidate
            break

    index = window["index"]
    elapsed = local - window["start_ms"]
    transition_ms = window["transition_ms"]

    # A transition needs something to come *from*. On the very first page of a
    # non-looping project there is no previous page, so it plays as a cut.
    has_previous = index > 0 or (len(pages) > 1 and bool(playback.get("loop", True)))
    previous_index = (index - 1) if index > 0 else (len(pages) - 1 if has_previous else None)

    if transition_ms > 0 and elapsed < transition_ms and previous_index is not None:
        progress = elapsed / float(transition_ms)
        transition_type = window["transition_type"]
    else:
        progress = 1.0
        transition_type = "cut"
        previous_index = None

    return {
        "mode": "pages",
        "time_ms": local,
        "loop_ms": total,
        "page_index": index,
        "page": pages[index],
        "previous_index": previous_index,
        "previous_page": pages[previous_index] if previous_index is not None else None,
        "transition_type": transition_type,
        "transition_progress": progress,
        "scroll": None,
    }


# ---- Scroll --------------------------------------------------------------

def _scroll_page(project: dict) -> dict | None:
    pages = project.get("pages") or []
    return pages[0] if pages else None


def scroll_config(project: dict) -> dict:
    """Effective scroll settings: the first page's scroll block, defaulted."""
    page = _scroll_page(project)
    scroll = (page or {}).get("scroll") or {}
    return models.normalize_scroll(scroll)


def scroll_travel_px(project: dict) -> float:
    """Distance one loop must cover.

    Scroll mode lays every card out in one continuous strip (see
    ``grid.strip_extent``), so travel is measured against the strip length, not
    the canvas-sized static grid.

    Seamless looping travels exactly the strip length, so the duplicated tail
    lines up with the head and there is no visible seam. A non-looping scroll
    travels only strip-minus-canvas — just enough to reveal everything once.
    """
    page = _scroll_page(project)
    canvas = project.get("canvas") or {}
    if page is None:
        return 0.0

    scroll = scroll_config(project)
    horizontal = scroll["direction"] in ("left", "right")
    extent = grid.strip_extent(page, canvas, horizontal, scroll["item_gap"])
    if extent <= 0:
        return 0.0

    if scroll["loop"]:
        return extent
    visible = float(canvas.get("width" if horizontal else "height", 0) or 0)
    return max(0.0, extent - visible)


def scroll_loop_duration_ms(project: dict) -> int:
    """One scroll cycle, including edge pauses, in whole milliseconds."""
    scroll = scroll_config(project)
    travel = scroll_travel_px(project)
    speed = max(1e-9, float(scroll["speed_px_per_second"]))
    moving_ms = (travel / speed) * 1000.0
    pause_ms = float(scroll["edge_pause_ms"])
    # A seamless loop pauses once per cycle; a ping-pong reveal pauses at both ends.
    pauses = pause_ms if scroll["loop"] else pause_ms * 2
    return js_round(moving_ms + pauses)


def scroll_state_at(project: dict, time_ms) -> dict:
    """Scroll offset at ``time_ms``.

    ``offset_x/offset_y`` is the translation to apply to the content group.
    Direction ``left`` moves content toward negative x (the classic ticker).
    """
    scroll = scroll_config(project)
    page = _scroll_page(project)
    travel = scroll_travel_px(project)
    speed = max(1e-9, float(scroll["speed_px_per_second"]))
    pause_ms = float(scroll["edge_pause_ms"])
    moving_ms = (travel / speed) * 1000.0
    total = scroll_loop_duration_ms(project)

    if total <= 0 or travel <= 0:
        progress = 0.0
        local = 0.0
    else:
        local = _normalize_time(time_ms, total, True)
        if scroll["loop"]:
            # Pause happens at the start of the cycle, then travel.
            if local < pause_ms:
                progress = 0.0
            else:
                progress = min(1.0, (local - pause_ms) / max(1e-9, moving_ms))
        else:
            # pause -> travel -> pause, then repeat from the top.
            if local < pause_ms:
                progress = 0.0
            elif local < pause_ms + moving_ms:
                progress = (local - pause_ms) / max(1e-9, moving_ms)
            else:
                progress = 1.0

    distance = travel * progress
    direction = scroll["direction"]
    offset_x = offset_y = 0.0
    if direction == "left":
        offset_x = -distance
    elif direction == "right":
        offset_x = distance
    elif direction == "up":
        offset_y = -distance
    else:  # down
        offset_y = distance

    return {
        "mode": "scroll",
        "time_ms": local,
        "loop_ms": total,
        "page_index": 0,
        "page": page,
        "previous_index": None,
        "previous_page": None,
        "transition_type": "cut",
        "transition_progress": 1.0,
        "scroll": {
            "direction": direction,
            "offset_x": offset_x,
            "offset_y": offset_y,
            "distance": distance,
            "travel": travel,
            "progress": progress,
            "loop": scroll["loop"],
            "speed_px_per_second": scroll["speed_px_per_second"],
        },
    }


# ---- Entry point ---------------------------------------------------------

def state_at(project: dict, time_ms) -> dict:
    """Complete render state at ``time_ms``. Deterministic and side-effect free."""
    playback = project.get("playback") or {}
    if playback.get("mode") == "scroll":
        return scroll_state_at(project, time_ms)
    return pages_state_at(project, time_ms)


def frame_times(project: dict, fps: int, duration_ms=None) -> list[int]:
    """Frame timestamps for an export.

    Defaults to exactly one loop. Frame ``n`` sits at ``round(n * 1000 / fps)``,
    so a 15fps 5s export is 75 frames — never 74 or 76 from accumulated float
    drift.
    """
    fps = max(1, int(fps))
    total = int(duration_ms if duration_ms is not None else loop_duration_ms(project))
    if total <= 0:
        return [0]
    count = max(1, js_round(total * fps / 1000.0))
    return [js_round(index * 1000.0 / fps) for index in range(count)]


def frame_count(project: dict, fps: int, duration_ms=None) -> int:
    """How many frames an export will produce (for the pre-export estimate)."""
    return len(frame_times(project, fps, duration_ms))
