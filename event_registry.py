"""
event_registry.py — Dynamic Event Registry for TikTokMCIntegrator

Defines metadata for ALL TikTokLive events so they can be dynamically
enabled/configured from the dashboard without touching code.

Usage:
    from event_registry import EVENT_REGISTRY, get_event_categories, get_registry_for_api
"""

# Import all events from TikTokLive
from TikTokLive.events import (
    AccessControlEvent,
    AccessRecallEvent,
    BarrageEvent,
    BoostCardEvent,
    BottomEvent,
    CapsuleEvent,
    CaptionEvent,
    CommentEvent,
    ConnectEvent,
    ControlEvent,
    CustomEvent,
    DisconnectEvent,
    EmoteChatEvent,
    EnvelopeEvent,
    FollowEvent,
    GameRankNotifyEvent,
    GiftBroadcastEvent,
    GiftDynamicRestrictionEvent,
    GiftEvent,
    GiftPanelUpdateEvent,
    GiftPromptEvent,
    GoalUpdateEvent,
    GuideEvent,
    HourlyRankRewardEvent,
    ImDeleteEvent,
    InRoomBannerEvent,
    JoinEvent,
    LikeEvent,
    LinkEvent,
    LinkLayerEvent,
    LinkMicArmiesEvent,
    LinkMicBattleEvent,
    LinkMicBattleItemCardEvent,
    LinkMicBattlePunishFinishEvent,
    LinkMicFanTicketMethodEvent,
    LinkMicLayoutStateEvent,
    LinkMicMethodEvent,
    LinkStateEvent,
    LinkmicBattleTaskEvent,
    LiveEndEvent,
    LiveGameIntroEvent,
    LiveIntroEvent,
    LivePauseEvent,
    LiveUnpauseEvent,
    MarqueeAnnouncementEvent,
    MessageDetectEvent,
    NoticeEvent,
    OecLiveShoppingEvent,
    PartnershipDropsUpdateEvent,
    PartnershipGameOfflineEvent,
    PartnershipPunishEvent,
    PerceptionEvent,
    PollEvent,
    QuestionNewEvent,
    RankTextEvent,
    RankUpdateEvent,
    RoomEvent,
    RoomNotifyEvent,
    RoomPinEvent,
    RoomUserSeqEvent,
    RoomVerifyEvent,
    ShareEvent,
    SocialEvent,
    SpeakerEvent,
    SubNotifyEvent,
    SubPinEventEvent,
    SuperFanBoxEvent,
    SuperFanEvent,
    SuperFanJoinEvent,
    SystemEvent,
    ToastEvent,
    UnauthorizedMemberEvent,
    ViewerPicksUpdateEvent,
)
from TikTokLive.events.custom_events import (
    SuperFanEvent as CustomSuperFanEvent,
    SuperFanBoxEvent as CustomSuperFanBoxEvent,
)

# ── Category definitions with icons ──────────────────────────────────────────
CATEGORY_META = {
    "gifts":        {"icon": "🎁", "label": "Gifts", "color": "#f0b232"},
    "social":       {"icon": "📤", "label": "Social", "color": "#00f2ea"},
    "chat":         {"icon": "💬", "label": "Chat", "color": "#5865f2"},
    "room":         {"icon": "👥", "label": "Room", "color": "#3ba55c"},
    "battle":       {"icon": "⚔️", "label": "Battle", "color": "#ed4245"},
    "subscription": {"icon": "⭐", "label": "Subscription", "color": "#a855f7"},
    "interactive":  {"icon": "🎮", "label": "Interactive", "color": "#2196f3"},
    "moderation":   {"icon": "🛡️", "label": "Moderation", "color": "#ff5722"},
    "display":      {"icon": "🖥️", "label": "Display", "color": "#607d8b"},
    "system":       {"icon": "⚙️", "label": "System", "color": "#545b70"},
}


def _evt(event_class, name, description, category, template_vars, priority="medium", infra=False):
    """Helper to build a registry entry."""
    return {
        "class": event_class,
        "name": name,
        "description": description,
        "category": category,
        "template_vars": template_vars,
        "priority": priority,
        "infra": infra,  # True = system infrastructure event, not user-configurable
    }


# ── Full Event Registry ─────────────────────────────────────────────────────
EVENT_REGISTRY = {
    # ═══════════════ GIFT EVENTS ═══════════════
    "GiftEvent": _evt(
        GiftEvent,
        "Gift Received",
        "Fires when someone sends a gift. Most popular event for Minecraft integrations.",
        "gifts",
        ["user", "mc", "gift_name", "gift_id", "amount", "repeat_count", "total_coin", "diamond_count"],
        "high",
    ),
    "GiftBroadcastEvent": _evt(
        GiftBroadcastEvent,
        "Gift Broadcast",
        "Broadcast notification when a high-value gift is sent in the room.",
        "gifts",
        ["user", "mc", "gift_name", "amount"],
        "medium",
    ),
    "GiftPromptEvent": _evt(
        GiftPromptEvent,
        "Gift Prompt",
        "Fires when the gift prompt/reminder is shown to viewers.",
        "gifts",
        ["user", "mc"],
        "low",
    ),
    "GiftPanelUpdateEvent": _evt(
        GiftPanelUpdateEvent,
        "Gift Panel Update",
        "Fires when the gift panel UI is updated (new gifts available, etc).",
        "gifts",
        [],
        "low",
    ),
    "GiftDynamicRestrictionEvent": _evt(
        GiftDynamicRestrictionEvent,
        "Gift Restriction Change",
        "Fires when gift sending restrictions change (e.g., new user limits).",
        "gifts",
        [],
        "low",
    ),
    "BoostCardEvent": _evt(
        BoostCardEvent,
        "Boost Card",
        "Fires when a boost card is activated in the stream.",
        "gifts",
        ["user", "mc"],
        "low",
    ),

    # ═══════════════ SOCIAL EVENTS ═══════════════
    "FollowEvent": _evt(
        FollowEvent,
        "New Follow",
        "Fires when someone follows the streamer. Great for welcome messages.",
        "social",
        ["user", "mc", "amount"],
        "high",
    ),
    "LikeEvent": _evt(
        LikeEvent,
        "Like",
        "Fires when someone likes the stream. Track total likes for milestones.",
        "social",
        ["user", "mc", "total_likes", "amount"],
        "high",
    ),
    "ShareEvent": _evt(
        ShareEvent,
        "Share",
        "Fires when someone shares the stream to their followers.",
        "social",
        ["user", "mc"],
        "medium",
    ),
    "JoinEvent": _evt(
        JoinEvent,
        "User Joined",
        "Fires when someone joins the live room.",
        "social",
        ["user", "mc"],
        "medium",
    ),
    "SocialEvent": _evt(
        SocialEvent,
        "Social Interaction",
        "Generic social interaction event (covers multiple social actions).",
        "social",
        ["user", "mc"],
        "low",
    ),

    # ═══════════════ CHAT EVENTS ═══════════════
    "CommentEvent": _evt(
        CommentEvent,
        "Chat Comment",
        "Fires on every chat message. Use for keyword commands and chat reactions.",
        "chat",
        ["user", "mc", "comment", "tag"],
        "high",
    ),
    "EmoteChatEvent": _evt(
        EmoteChatEvent,
        "Emote Chat",
        "Fires when someone sends an emote/sticker in chat.",
        "chat",
        ["user", "mc"],
        "low",
    ),
    "QuestionNewEvent": _evt(
        QuestionNewEvent,
        "New Question",
        "Fires when a viewer submits a question via the Q&A feature.",
        "chat",
        ["user", "mc", "comment"],
        "medium",
    ),
    "MessageDetectEvent": _evt(
        MessageDetectEvent,
        "Message Detect",
        "Internal message detection event from TikTok's moderation system.",
        "chat",
        ["user", "mc"],
        "low",
    ),

    # ═══════════════ ROOM EVENTS ═══════════════
    "ConnectEvent": _evt(
        ConnectEvent,
        "Connected",
        "Fires when the bot connects to the TikTok live stream.",
        "room",
        ["user", "mc"],
        "high",
        infra=True,
    ),
    "DisconnectEvent": _evt(
        DisconnectEvent,
        "Disconnected",
        "Fires when the bot disconnects from the stream.",
        "room",
        [],
        "high",
        infra=True,
    ),
    "RoomUserSeqEvent": _evt(
        RoomUserSeqEvent,
        "Viewer Count Update",
        "Periodic viewer count updates. Used for live viewer display.",
        "room",
        [],
        "high",
        infra=True,
    ),
    "RoomEvent": _evt(
        RoomEvent,
        "Room Info",
        "Fires when room information is received (initial room data).",
        "room",
        [],
        "low",
    ),
    "RoomNotifyEvent": _evt(
        RoomNotifyEvent,
        "Room Notification",
        "In-room notification banners (e.g., trending, milestones).",
        "room",
        ["user", "mc"],
        "low",
    ),
    "RoomPinEvent": _evt(
        RoomPinEvent,
        "Room Pin",
        "Fires when a message is pinned in the room.",
        "room",
        ["user", "mc", "comment"],
        "medium",
    ),
    "RoomVerifyEvent": _evt(
        RoomVerifyEvent,
        "Room Verify",
        "Room verification event from TikTok.",
        "room",
        [],
        "low",
    ),
    "LiveEndEvent": _evt(
        LiveEndEvent,
        "Live Ended",
        "Fires when the TikTok live stream ends.",
        "room",
        [],
        "high",
    ),
    "LiveIntroEvent": _evt(
        LiveIntroEvent,
        "Live Intro",
        "Fires when the stream intro is displayed.",
        "room",
        [],
        "low",
    ),
    "LiveGameIntroEvent": _evt(
        LiveGameIntroEvent,
        "Game Intro",
        "Fires when a game intro is displayed in the live stream.",
        "room",
        [],
        "low",
    ),
    "LivePauseEvent": _evt(
        LivePauseEvent,
        "Live Paused",
        "Fires when the stream is paused (e.g., for ads or break).",
        "room",
        [],
        "medium",
    ),
    "LiveUnpauseEvent": _evt(
        LiveUnpauseEvent,
        "Live Unpaused",
        "Fires when the stream resumes after being paused.",
        "room",
        [],
        "medium",
    ),

    # ═══════════════ BATTLE EVENTS ═══════════════
    "LinkMicBattleEvent": _evt(
        LinkMicBattleEvent,
        "Link Mic Battle",
        "Fires when a PK/battle starts or updates between streamers.",
        "battle",
        ["user", "mc"],
        "medium",
    ),
    "LinkMicBattleItemCardEvent": _evt(
        LinkMicBattleItemCardEvent,
        "Battle Power-Up",
        "Fires when a battle item card/power-up is obtained, awarded, used, or applied.",
        "battle",
        ["battle_id", "msg_type", "award_reason"],
        "medium",
    ),
    "LinkMicArmiesEvent": _evt(
        LinkMicArmiesEvent,
        "Battle Armies",
        "Fires when battle army/team information updates.",
        "battle",
        ["user", "mc"],
        "low",
    ),
    "LinkMicBattlePunishFinishEvent": _evt(
        LinkMicBattlePunishFinishEvent,
        "Battle Punish End",
        "Fires when the punishment phase of a battle ends.",
        "battle",
        ["user", "mc"],
        "low",
    ),
    "LinkmicBattleTaskEvent": _evt(
        LinkmicBattleTaskEvent,
        "Battle Task",
        "Fires when a battle task/goal is set or updated.",
        "battle",
        [],
        "low",
    ),
    "LinkMicFanTicketMethodEvent": _evt(
        LinkMicFanTicketMethodEvent,
        "Fan Ticket",
        "Fires when fan tickets are used during a battle.",
        "battle",
        ["user", "mc"],
        "low",
    ),
    "LinkMicLayoutStateEvent": _evt(
        LinkMicLayoutStateEvent,
        "Mic Layout State",
        "Fires when the link mic layout state changes.",
        "battle",
        [],
        "low",
    ),
    "LinkMicMethodEvent": _evt(
        LinkMicMethodEvent,
        "Link Mic Method",
        "General link mic method event (connection changes, etc).",
        "battle",
        [],
        "low",
    ),
    "LinkStateEvent": _evt(
        LinkStateEvent,
        "Link State",
        "Fires when the link connection state changes.",
        "battle",
        [],
        "low",
    ),
    "LinkEvent": _evt(
        LinkEvent,
        "Link Event",
        "General link/multi-guest event.",
        "battle",
        [],
        "low",
    ),
    "LinkLayerEvent": _evt(
        LinkLayerEvent,
        "Link Layer",
        "Low-level link layer event.",
        "battle",
        [],
        "low",
    ),

    # ═══════════════ SUBSCRIPTION EVENTS ═══════════════
    "SubNotifyEvent": _evt(
        SubNotifyEvent,
        "New Subscription",
        "Fires when someone subscribes to the streamer (paid subscription).",
        "subscription",
        ["user", "mc", "amount"],
        "high",
    ),
    "SubPinEventEvent": _evt(
        SubPinEventEvent,
        "Sub Pin Event",
        "Fires when a subscription pin event occurs.",
        "subscription",
        ["user", "mc"],
        "low",
    ),
    "SuperFanEvent": _evt(
        SuperFanEvent,
        "New SuperFan",
        "Fires when someone becomes a new superfan. Custom TikTokLive event.",
        "subscription",
        ["user", "mc", "amount"],
        "high",
    ),
    "SuperFanBoxEvent": _evt(
        SuperFanBoxEvent,
        "SuperFan Gift Box",
        "Fires when someone gifts a superfan box/bundle to the stream. Sender-side only triggers actions; claim/open events are logged separately.",
        "subscription",
        ["user", "mc", "amount", "box_phase", "envelope_id", "sender_id", "sender_name", "diamond_count", "people_count"],
        "high",
    ),
    "SuperFanJoinEvent": _evt(
        SuperFanJoinEvent,
        "SuperFan Joined",
        "Fires when an existing superfan joins the live room.",
        "subscription",
        ["user", "mc"],
        "medium",
    ),

    # ═══════════════ INTERACTIVE EVENTS ═══════════════
    "PollEvent": _evt(
        PollEvent,
        "Poll",
        "Fires when a poll is created or updated in the stream.",
        "interactive",
        ["comment"],
        "medium",
    ),
    "CapsuleEvent": _evt(
        CapsuleEvent,
        "Capsule",
        "Fires when a capsule/mystery box event occurs.",
        "interactive",
        ["user", "mc"],
        "low",
    ),
    "EnvelopeEvent": _evt(
        EnvelopeEvent,
        "Red Envelope",
        "Fires when a red envelope (gift rain) event occurs.",
        "interactive",
        ["user", "mc"],
        "medium",
    ),
    "GoalUpdateEvent": _evt(
        GoalUpdateEvent,
        "Goal Update",
        "Fires when a stream goal progress is updated.",
        "interactive",
        [],
        "medium",
    ),
    "BarrageEvent": _evt(
        BarrageEvent,
        "Barrage",
        "Fires for barrage/bullet screen comments (special comment style).",
        "interactive",
        ["user", "mc", "comment"],
        "low",
    ),
    "HourlyRankRewardEvent": _evt(
        HourlyRankRewardEvent,
        "Hourly Rank Reward",
        "Fires when the streamer receives an hourly ranking reward.",
        "interactive",
        [],
        "low",
    ),
    "RankUpdateEvent": _evt(
        RankUpdateEvent,
        "Rank Update",
        "Fires when the streamer's ranking changes.",
        "interactive",
        [],
        "low",
    ),
    "RankTextEvent": _evt(
        RankTextEvent,
        "Rank Text",
        "Fires when rank display text is updated.",
        "interactive",
        [],
        "low",
    ),
    "ViewerPicksUpdateEvent": _evt(
        ViewerPicksUpdateEvent,
        "Viewer Picks Update",
        "Fires when viewer picks/selections are updated.",
        "interactive",
        [],
        "low",
    ),
    "PartnershipDropsUpdateEvent": _evt(
        PartnershipDropsUpdateEvent,
        "Partnership Drops",
        "Fires when partnership drops/rewards are updated.",
        "interactive",
        [],
        "low",
    ),
    "PartnershipGameOfflineEvent": _evt(
        PartnershipGameOfflineEvent,
        "Game Offline",
        "Fires when a partnership game goes offline.",
        "interactive",
        [],
        "low",
    ),
    "OecLiveShoppingEvent": _evt(
        OecLiveShoppingEvent,
        "Live Shopping",
        "Fires when a live shopping/commerce event occurs.",
        "interactive",
        [],
        "low",
    ),

    # ═══════════════ MODERATION EVENTS ═══════════════
    "ImDeleteEvent": _evt(
        ImDeleteEvent,
        "Message Deleted",
        "Fires when a chat message is deleted by moderation.",
        "moderation",
        ["user", "mc"],
        "medium",
    ),
    "AccessControlEvent": _evt(
        AccessControlEvent,
        "Access Control",
        "Fires when access control settings change (e.g., muting users).",
        "moderation",
        ["user", "mc"],
        "low",
    ),
    "AccessRecallEvent": _evt(
        AccessRecallEvent,
        "Access Recall",
        "Fires when an access control action is recalled/reversed.",
        "moderation",
        [],
        "low",
    ),
    "ControlEvent": _evt(
        ControlEvent,
        "Stream Control",
        "Fires when stream control events occur (admin actions).",
        "moderation",
        [],
        "low",
    ),
    "PerceptionEvent": _evt(
        PerceptionEvent,
        "Content Perception",
        "Fires on content perception/moderation flags.",
        "moderation",
        [],
        "low",
    ),
    "UnauthorizedMemberEvent": _evt(
        UnauthorizedMemberEvent,
        "Unauthorized Member",
        "Fires when an unauthorized member is detected.",
        "moderation",
        ["user", "mc"],
        "low",
    ),
    "PartnershipPunishEvent": _evt(
        PartnershipPunishEvent,
        "Partnership Punish",
        "Fires when a partnership punishment is applied.",
        "moderation",
        [],
        "low",
    ),

    # ═══════════════ DISPLAY EVENTS ═══════════════
    "CaptionEvent": _evt(
        CaptionEvent,
        "Caption",
        "Fires when captions/subtitles are generated for the stream.",
        "display",
        ["comment"],
        "low",
    ),
    "GuideEvent": _evt(
        GuideEvent,
        "Guide",
        "Fires when a guide/tooltip overlay is displayed.",
        "display",
        [],
        "low",
    ),
    "ToastEvent": _evt(
        ToastEvent,
        "Toast Notification",
        "Fires when a toast notification appears in the stream UI.",
        "display",
        [],
        "low",
    ),
    "MarqueeAnnouncementEvent": _evt(
        MarqueeAnnouncementEvent,
        "Marquee Announcement",
        "Fires when a scrolling marquee announcement is displayed.",
        "display",
        ["comment"],
        "low",
    ),
    "NoticeEvent": _evt(
        NoticeEvent,
        "Notice",
        "Fires when a notice/alert is displayed in the room.",
        "display",
        ["comment"],
        "low",
    ),
    "InRoomBannerEvent": _evt(
        InRoomBannerEvent,
        "In-Room Banner",
        "Fires when an in-room banner is displayed (promotions, etc).",
        "display",
        [],
        "low",
    ),

    # ═══════════════ SYSTEM EVENTS ═══════════════
    "CustomEvent": _evt(
        CustomEvent,
        "Custom Event",
        "Generic custom event from TikTokLive.",
        "system",
        [],
        "low",
    ),
    "SystemEvent": _evt(
        SystemEvent,
        "System Event",
        "System-level event from TikTok.",
        "system",
        [],
        "low",
    ),
    "BottomEvent": _evt(
        BottomEvent,
        "Bottom Bar",
        "Fires for bottom bar/panel events in the stream UI.",
        "system",
        [],
        "low",
    ),
    "GameRankNotifyEvent": _evt(
        GameRankNotifyEvent,
        "Game Rank Notify",
        "Fires when a game ranking notification is sent.",
        "system",
        [],
        "low",
    ),
    "SpeakerEvent": _evt(
        SpeakerEvent,
        "Speaker",
        "Fires for speaker/audio events in the stream.",
        "system",
        [],
        "low",
    ),
}


# ── API Functions ────────────────────────────────────────────────────────────

def get_event_categories():
    """Return category metadata for the frontend."""
    return CATEGORY_META


def get_registry_for_api():
    """Return JSON-safe registry (without class references).

    Returns:
        dict: event_key -> {name, description, category, template_vars, priority, infra}
    """
    result = {}
    for key, entry in EVENT_REGISTRY.items():
        result[key] = {
            "name": entry["name"],
            "description": entry["description"],
            "category": entry["category"],
            "template_vars": entry["template_vars"],
            "priority": entry["priority"],
            "infra": entry.get("infra", False),
        }
    return result


def get_registry_with_categories():
    """Return registry grouped by category for the frontend browser."""
    registry = get_registry_for_api()
    categories = get_event_categories()

    grouped = {}
    for cat_key, cat_meta in categories.items():
        events = {k: v for k, v in registry.items() if v["category"] == cat_key}
        if events:
            grouped[cat_key] = {
                "meta": cat_meta,
                "events": events,
            }
    return grouped


def get_event_class(event_key):
    """Get the actual TikTokLive event class by registry key.

    Args:
        event_key: string key like 'GiftEvent', 'FollowEvent', etc.

    Returns:
        The event class, or None if not found.
    """
    entry = EVENT_REGISTRY.get(event_key)
    if entry:
        return entry["class"]
    return None
