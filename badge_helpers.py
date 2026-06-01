"""Badge extraction helpers."""


def _extract_scene_type(badge) -> str:
    """Extract and clean scene type name from badge. Returns '' if unknown."""
    scene = getattr(badge, "scene_type", None) or getattr(badge, "badge_scene", None)
    if scene is None:
        return ""
    scene_name = getattr(scene, "name", None) or str(scene)
    scene_name = str(scene_name).replace("BADGE_SCENE_TYPE_", "").upper()
    if "." in scene_name:
        scene_name = scene_name.rsplit(".", 1)[-1]
    return scene_name if scene_name not in ("UNKNOWN", "") else ""


def _extract_badge_level(badge) -> int | None:
    """Extract level from privilege_log_extra."""
    log_extra = getattr(badge, "privilege_log_extra", None) or getattr(badge, "log_extra", None)
    badge_level = getattr(log_extra, "level", None) if log_extra else None
    try:
        return int(badge_level) if badge_level is not None else None
    except (ValueError, TypeError):
        return None


def _extract_combine_icon(combine) -> str:
    """Extract icon URL from combine.badge.icon.url_list."""
    try:
        combine_icon = getattr(combine, "icon", None)
        if combine_icon:
            url_list = getattr(combine_icon, "url_list", None)
            if url_list and len(url_list) > 0:
                return url_list[0]
    except Exception:
        pass
    return ""


def _extract_combine_text(combine) -> str:
    """Extract level text from combine.text or combine.str."""
    try:
        # Try combine.text.pieces first
        combine_text = getattr(combine, "text", None)
        if combine_text:
            pieces = getattr(combine_text, "pieces", None)
            if pieces and len(pieces) > 0:
                return str(pieces[0])
            # Try default_pattern if pieces empty
            default_pattern = getattr(combine_text, "default_pattern", "")
            if default_pattern:
                return str(default_pattern)
        
        # Fallback: try combine.str (plain string field)
        combine_str = getattr(combine, "str", None)
        if combine_str:
            return str(combine_str)
    except Exception as e:
        print(f"[DEBUG] Badge text extraction error: {e}")
    return ""


def _extract_combine_colors(combine) -> tuple[str, str]:
    """Extract (bg_color, border_color) from combine.background."""
    try:
        bg = getattr(combine, "background", None)
        if bg:
            bg_color = getattr(bg, "background_color_code", "") or ""
            border_color = getattr(bg, "border_color_code", "") or ""
            return bg_color, border_color
    except Exception:
        pass
    return "", ""


def _extract_image_icon(badge) -> str:
    """Extract icon URL from image badge type."""
    try:
        image_badge = getattr(badge, "image", None)
        if image_badge:
            image_model = getattr(image_badge, "image", None)
            if image_model:
                url_list = getattr(image_model, "url_list", None)
                if url_list and len(url_list) > 0:
                    return url_list[0]
    except Exception:
        pass
    return ""
