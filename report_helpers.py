"""Report generation helpers."""

import os
import json
import datetime

from utils import load_json
from constants import BASE_DIR


def load_stream_state():
    """Load stream state from file."""
    state_file = os.path.join(BASE_DIR, "stream_state.json")
    if os.path.exists(state_file):
        try:
            return load_json(state_file) or {}
        except Exception:
            pass
    return {}


def calculate_stats(gifts, follows, chat):
    """Calculate report statistics from logs."""
    total_coins = sum(g.get("total_coins", 0) for g in gifts)

    # Top gifters
    gifter_totals = {}
    for g in gifts:
        sender = g.get("sender", "Unknown")
        gifter_totals[sender] = gifter_totals.get(sender, 0) + g.get("total_coins", 0)
    top_gifters = sorted(gifter_totals.items(), key=lambda x: x[1], reverse=True)[:10]

    # Gift breakdown
    gift_counts = {}
    for g in gifts:
        name = g.get("gift_name", "Unknown")
        qty = g.get("repeat_count", 1)
        gift_counts[name] = gift_counts.get(name, 0) + qty

    # Unique chatters
    unique_chatters = len(set(c.get("unique_id", "") for c in chat if c.get("unique_id")))

    return {
        "total_coins": total_coins,
        "top_gifters": top_gifters,
        "gift_counts": gift_counts,
        "unique_chatters": unique_chatters,
    }


def format_report_header(state, now):
    """Format report header with stream info."""
    lines = [
        "=" * 50,
        "  STREAM REPORT",
        "=" * 50,
        "",
        f"  Date:       {now.strftime('%Y-%m-%d %H:%M')}",
        f"  Started:    {state.get('started_at', 'Unknown')}",
        f"  Username:   @{state.get('username', 'Unknown')}",
        f"  Room ID:    {state.get('room_id', 'unknown')}",
        "",
    ]
    return lines


def format_report_summary(stats, gifts, follows, chat):
    """Format summary section."""
    lines = [
        "-" * 50,
        "  SUMMARY",
        "-" * 50,
        f"  Total Gifts:        {len(gifts)}",
        f"  Total Coins:        {stats['total_coins']}",
        f"  New Followers:      {len(follows)}",
        f"  Chat Messages:      {len(chat)}",
        f"  Unique Chatters:    {stats['unique_chatters']}",
        "",
    ]
    return lines


def format_report_top_gifters(top_gifters):
    """Format top gifters section."""
    if not top_gifters:
        return []
    lines = [
        "-" * 50,
        "  TOP GIFTERS",
        "-" * 50,
    ]
    for i, (name, coins) in enumerate(top_gifters, 1):
        lines.append(f"  {i:>2}. {name:<25} {coins} coins")
    lines.append("")
    return lines


def format_report_gift_breakdown(gift_counts):
    """Format gift breakdown section."""
    if not gift_counts:
        return []
    lines = [
        "-" * 50,
        "  GIFT BREAKDOWN",
        "-" * 50,
    ]
    for name, qty in sorted(gift_counts.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"  {name:<30} x{qty}")
    lines.append("")
    return lines


def format_report_followers(follows):
    """Format new followers section."""
    if not follows:
        return []
    lines = [
        "-" * 50,
        "  NEW FOLLOWERS",
        "-" * 50,
    ]
    for f in follows:
        nick = f.get("nick", "Unknown")
        uid = f.get("unique_id", "")
        lines.append(f"  @{uid} ({nick})")
    lines.append("")
    return lines


def format_report_chat_history(chat):
    """Format chat history section."""
    if not chat:
        return []
    lines = [
        "-" * 50,
        "  CHAT HISTORY",
        "-" * 50,
    ]
    for c in chat:
        tags = c.get("tags", "newbie").upper().replace(",", "][")
        nick = c.get("nick", "?")
        comment = c.get("comment", "")
        lines.append(f"  [{tags}] {nick}: {comment}")
    lines.append("")
    return lines
