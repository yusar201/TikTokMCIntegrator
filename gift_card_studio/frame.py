"""Compose one timeline frame into a complete SVG.

This is the layer that turns a ``playback.state_at`` result into pixels-ready
markup: page bodies, cross-fades, slides, pixel wipes, and the duplicated
scroll strip that hides a seamless loop's seam.

**Why it is its own module.** It started inside ``exporter.py``, which made
transition composition export-only. The OBS overlay renders from the JS side, so
the exported GIF and the live overlay would have drifted the moment either
gained a transition the other lacked — the exact failure the shared-renderer
decision exists to prevent. Frame composition now sits beside the renderer and
has a JS mirror (``static/gift-studio/frame.js``) held to byte-identical output
by ``tests/test_gift_card_studio_frame_parity.py``.

Pure module: no I/O, no rasterizer, no Pillow.
"""
from __future__ import annotations

from . import playback, renderer
from .numeric import js_round

# Pixel wipe reveals in discrete columns rather than a smooth edge, matching the
# stepped aesthetic of the panels themselves.
PIXEL_WIPE_STEPS = 16


def _lerp(a, b, t):
    return a + (b - a) * float(t)


def _round(value) -> str:
    return renderer._round(value)  # noqa: SLF001 - same package, single source of rounding


def svg_header(width, height) -> str:
    w = _round(width)
    h = _round(height)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}">'
    )


def scroll_frame_body(page, canvas, scroll, context=None) -> str:
    """The scrolling strip, translated, plus the trailing copy for a loop.

    A seamless loop needs a second copy of the strip positioned exactly one
    travel-length behind the first, so as the first walks off screen the second
    is already filling the gap. Without it the loop shows empty canvas at the
    seam.
    """
    horizontal = scroll["direction"] in ("left", "right")
    item_gap = (page.get("scroll") or {}).get("item_gap")
    body = renderer.render_strip_body(page, canvas, context, horizontal, item_gap)
    if not body:
        return ""

    dx = scroll["offset_x"]
    dy = scroll["offset_y"]
    parts = [f'<g transform="translate({_round(dx)} {_round(dy)})">{body}</g>']

    if scroll["loop"]:
        travel = scroll["travel"]
        follow_x, follow_y = dx, dy
        # The copy trails in the direction the content came from.
        if scroll["direction"] == "left":
            follow_x = dx + travel
        elif scroll["direction"] == "right":
            follow_x = dx - travel
        elif scroll["direction"] == "up":
            follow_y = dy + travel
        else:
            follow_y = dy - travel
        parts.append(
            f'<g transform="translate({_round(follow_x)} {_round(follow_y)})">{body}</g>'
        )

    return "".join(parts)


def transition_body(current, outgoing, transition, progress, width, height,
                    clip_id="wipe") -> str:
    """Compose two page bodies mid-transition.

    ``clip_id`` is caller-supplied so an embedding document with several frames
    on screen cannot collide on a duplicate SVG id.
    """
    progress = max(0.0, min(1.0, float(progress)))

    if transition == "fade":
        return (
            f'<g opacity="{_round(1.0 - progress)}">{outgoing}</g>'
            f'<g opacity="{_round(progress)}">{current}</g>'
        )

    if transition == "slide":
        out_dx = _lerp(0.0, -float(width), progress)
        in_dx = _lerp(float(width), 0.0, progress)
        return (
            f'<g transform="translate({_round(out_dx)} 0)">{outgoing}</g>'
            f'<g transform="translate({_round(in_dx)} 0)">{current}</g>'
        )

    # pixel_wipe — stepped reveal.
    revealed = max(0, min(PIXEL_WIPE_STEPS, js_round(progress * PIXEL_WIPE_STEPS)))
    wipe_width = float(width) * (revealed / PIXEL_WIPE_STEPS)
    if wipe_width <= 0:
        return outgoing
    return (
        f'{outgoing}<clipPath id="{clip_id}">'
        f'<rect x="0" y="0" width="{_round(wipe_width)}" height="{_round(height)}" />'
        f'</clipPath>'
        f'<g clip-path="url(#{clip_id})">{current}</g>'
    )


def frame_body(project: dict, time_ms, context=None, clip_id="wipe") -> str:
    """Inner markup for one frame — no ``<svg>`` wrapper, no background."""
    canvas = project.get("canvas") or {}
    state = playback.state_at(project, time_ms)

    if state["mode"] == "scroll":
        page = state["page"]
        if page is None:
            return ""
        return scroll_frame_body(page, canvas, state["scroll"], context)

    page = state["page"]
    if page is None:
        return ""

    current = renderer.render_page_body(page, canvas, context)
    previous_page = state["previous_page"]
    progress = float(state["transition_progress"])
    transition = state["transition_type"]

    if previous_page is None or transition == "cut" or progress >= 1.0:
        return current

    outgoing = renderer.render_page_body(previous_page, canvas, context)
    return transition_body(
        current, outgoing, transition, progress,
        canvas.get("width", 0), canvas.get("height", 0), clip_id,
    )


def frame_svg(project: dict, time_ms, context=None, clip_id="wipe") -> str:
    """Complete SVG document for one timeline frame."""
    canvas = project.get("canvas") or {}
    width = canvas.get("width", 1920)
    height = canvas.get("height", 1080)
    background = renderer._canvas_background(  # noqa: SLF001 - same package
        {"width": width, "height": height, "background": canvas.get("background")}
    )
    body = frame_body(project, time_ms, context, clip_id)
    return svg_header(width, height) + background + body + "</svg>"
