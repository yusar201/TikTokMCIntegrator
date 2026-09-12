"""Classify configured gift actions into draft card content.

The single most valuable signal in Khito's real config is the ``titlecustom``
command: it already carries the human-readable label he shows on stream.

    spawnsilverfish {mc} {amount*5} {user}
    titlecustom '{user}' {mc} {amount*5} Silverfish
                                        ^^^^^^^^^^ the label a viewer reads

So the drafter reuses that label as the card's main text instead of inventing
one from the command verb. When no ``titlecustom`` exists we fall back to the
action verb and mark lower confidence, which routes the card into the Studio's
"needs review" filter rather than shipping a wrong guess silently.

Pure module: stdlib only, no I/O, no config mutation.
"""
from __future__ import annotations

import re

# Placeholder tokens the bot substitutes at dispatch time. They must never leak
# into a rendered card label.
PLACEHOLDER = re.compile(r"\{[^}]*\}")

# Intents drive which action icon and template a draft card gets.
INTENT_MOB = "mob"
INTENT_ITEM = "item"
INTENT_EFFECT = "effect"
INTENT_EXPLOSIVE = "explosive"
INTENT_WORLD = "world"
INTENT_SCORE = "score"
INTENT_TELEPORT = "teleport"
INTENT_TIMER = "timer"
INTENT_TITLE = "title"
INTENT_CUSTOM = "custom"

INTENTS = (
    INTENT_MOB,
    INTENT_ITEM,
    INTENT_EFFECT,
    INTENT_EXPLOSIVE,
    INTENT_WORLD,
    INTENT_SCORE,
    INTENT_TELEPORT,
    INTENT_TIMER,
    INTENT_TITLE,
    INTENT_CUSTOM,
)

# Command verb -> intent. Grounded in the verbs actually present in config.yml.
VERB_INTENTS = {
    "spawnmob": INTENT_MOB,
    "randommob": INTENT_MOB,
    "spawnsilverfish": INTENT_MOB,
    "cow": INTENT_MOB,
    "summon": INTENT_MOB,
    "tntspawn": INTENT_EXPLOSIVE,
    "tntrain": INTENT_EXPLOSIVE,
    "lightningstrike": INTENT_EXPLOSIVE,
    "give": INTENT_ITEM,
    "diamondpick": INTENT_ITEM,
    "wskit": INTENT_ITEM,
    "clearinven": INTENT_ITEM,
    "randompotions": INTENT_EFFECT,
    "effect": INTENT_EFFECT,
    "cobwebtrap": INTENT_WORLD,
    "revealore": INTENT_WORLD,
    "surface": INTENT_WORLD,
    "fill": INTENT_WORLD,
    "setblock": INTENT_WORLD,
    "keepinventory": INTENT_WORLD,
    "setspawn": INTENT_TELEPORT,
    "rtp": INTENT_TELEPORT,
    "tp": INTENT_TELEPORT,
    "teleport": INTENT_TELEPORT,
    "score": INTENT_SCORE,
    "scoreboard": INTENT_SCORE,
    "helpwin": INTENT_SCORE,
    "rush": INTENT_SCORE,
    "chatgift": INTENT_TITLE,
    "titlecustom": INTENT_TITLE,
    "title": INTENT_TITLE,
}

# Nested-verb hints for `execute ... run <verb> ...` and modded summons.
NESTED_HINTS = (
    ("summon", INTENT_MOB),
    ("fill", INTENT_WORLD),
    ("setblock", INTENT_WORLD),
    ("give", INTENT_ITEM),
    ("effect", INTENT_EFFECT),
    ("tp", INTENT_TELEPORT),
)

# Words in an entity/item id that mean "this is really an explosive".
EXPLOSIVE_TOKENS = ("tnt", "nuclear", "bomb", "dynamite", "explos")

# Modded ids look like `namespace:entity_path`. The namespace is the *mod* name
# (`luckytntmod:` ships hundreds of non-explosive entities too), so explosive
# detection must only read the entity path — otherwise every entity from that
# mod is misread as a bomb.
NAMESPACED_ID = re.compile(r"\b[a-z0-9_]+:([a-z0-9_/.]+)")


def _explosive_tokens_in(text: str) -> bool:
    """True when the *entity path* of any id looks like an explosive.

    ``luckytntmod:nuclear_tnt``     -> True  (path ``nuclear_tnt``)
    ``luckytntmod:village_defense`` -> False (path ``village_defense``)
    """
    lowered = (text or "").lower()
    paths = NAMESPACED_ID.findall(lowered)
    if paths:
        return any(token in path for path in paths for token in EXPLOSIVE_TOKENS)
    # Vanilla / unnamespaced ids: fall back to the whole command text.
    return any(token in lowered for token in EXPLOSIVE_TOKENS)

# Suggested action icon per intent. These are *names*, resolved to real assets
# by the Studio; a missing icon leaves the layer empty rather than broken.
INTENT_ICONS = {
    INTENT_MOB: "mob",
    INTENT_ITEM: "item",
    INTENT_EFFECT: "potion",
    INTENT_EXPLOSIVE: "tnt",
    INTENT_WORLD: "world",
    INTENT_SCORE: "trophy",
    INTENT_TELEPORT: "portal",
    INTENT_TIMER: "clock",
    INTENT_TITLE: "chat",
    INTENT_CUSTOM: "",
}

CONFIDENCE_TITLE_LABEL = 0.9   # reused Khito's own on-stream label
CONFIDENCE_VERB = 0.6          # derived from a known command verb
CONFIDENCE_NESTED = 0.5        # derived from an execute/run inner verb
CONFIDENCE_UNKNOWN = 0.2       # nothing recognizable; needs human review
HIGH_CONFIDENCE = 0.8          # threshold for "approve all high-confidence"


def command_verb(command) -> str:
    """Leading verb of a command, stripped of any leading slash."""
    if not isinstance(command, str):
        return ""
    stripped = command.strip().lstrip("/")
    if not stripped:
        return ""
    return stripped.split()[0].lower()


def strip_placeholders(text) -> str:
    """Remove ``{...}`` tokens and collapse the resulting whitespace."""
    if not isinstance(text, str):
        return ""
    return re.sub(r"\s+", " ", PLACEHOLDER.sub(" ", text)).strip()


def title_label(command) -> str:
    """Human-readable label carried by a ``titlecustom``/``title`` command.

    ``titlecustom '{user}' {mc} {amount*5} Silverfish`` -> ``Silverfish``.
    Quoted segments are dropped along with placeholders, because the quoted part
    is the username, not the label.
    """
    if command_verb(command) not in ("titlecustom", "title", "chatgift"):
        return ""
    body = command.strip().lstrip("/")
    body = body[len(body.split()[0]):]              # drop the verb
    body = re.sub(r"'[^']*'|\"[^\"]*\"", " ", body)  # drop quoted username
    return strip_placeholders(body)


def _nested_intent(command: str) -> tuple[str, float]:
    """Intent for an ``execute ... run <verb>`` command."""
    lowered = command.lower()
    if " run " in lowered:
        tail = lowered.split(" run ", 1)[1]
        tail_verb = command_verb(tail)
        if tail_verb in VERB_INTENTS:
            intent = VERB_INTENTS[tail_verb]
            if intent == INTENT_MOB and _explosive_tokens_in(tail):
                return INTENT_EXPLOSIVE, CONFIDENCE_NESTED
            return intent, CONFIDENCE_NESTED
    for token, intent in NESTED_HINTS:
        if token in lowered:
            if intent == INTENT_MOB and _explosive_tokens_in(lowered):
                return INTENT_EXPLOSIVE, CONFIDENCE_NESTED
            return intent, CONFIDENCE_NESTED
    return INTENT_CUSTOM, CONFIDENCE_UNKNOWN


def classify_command(command) -> tuple[str, float]:
    """Return ``(intent, confidence)`` for one command string."""
    verb = command_verb(command)
    if not verb:
        return INTENT_CUSTOM, CONFIDENCE_UNKNOWN
    if verb == "execute":
        return _nested_intent(command)
    if verb in VERB_INTENTS:
        intent = VERB_INTENTS[verb]
        if intent == INTENT_MOB and _explosive_tokens_in(command):
            return INTENT_EXPLOSIVE, CONFIDENCE_VERB
        return intent, CONFIDENCE_VERB
    return INTENT_CUSTOM, CONFIDENCE_UNKNOWN


def classify_actions(commands) -> dict:
    """Classify a gift's whole command list into one draft intent.

    ``titlecustom`` is treated as *labelling*, not as the gift's real effect, so
    a gift whose only non-title command spawns a mob is classified ``mob`` — the
    title is what the viewer reads, the other command is what actually happens.
    """
    commands = [c for c in (commands or []) if isinstance(c, str) and c.strip()]
    if not commands:
        return {
            "intent": INTENT_CUSTOM,
            "confidence": CONFIDENCE_UNKNOWN,
            "label": "",
            "effect_commands": [],
            "title_commands": [],
        }

    title_commands, effect_commands = [], []
    for command in commands:
        if command_verb(command) in ("titlecustom", "title", "chatgift"):
            title_commands.append(command)
        else:
            effect_commands.append(command)

    label = next((title_label(c) for c in title_commands if title_label(c)), "")

    ranked = [classify_command(c) for c in effect_commands] or [
        (INTENT_TITLE, CONFIDENCE_VERB)
    ]
    # Prefer the most confident non-custom classification.
    ranked.sort(key=lambda pair: (pair[0] == INTENT_CUSTOM, -pair[1]))
    intent, confidence = ranked[0]

    if label:
        confidence = max(confidence, CONFIDENCE_TITLE_LABEL)

    return {
        "intent": intent,
        "confidence": round(min(1.0, confidence), 3),
        "label": label,
        "effect_commands": effect_commands,
        "title_commands": title_commands,
    }


def suggest_action_icon(intent) -> str:
    """Suggested action-icon name for an intent (may be empty = no icon)."""
    return INTENT_ICONS.get(intent, "")


def is_high_confidence(classification) -> bool:
    """True when a draft is safe to bulk-approve without per-card review."""
    return float((classification or {}).get("confidence", 0)) >= HIGH_CONFIDENCE


def draft_text(gift_name, classification, category="") -> dict:
    """Suggested main/secondary text for a card.

    * main      — the on-stream label when we have one, else the gift name
    * secondary — the coin category when it adds information
    """
    label = (classification or {}).get("label", "")
    name = (gift_name or "").strip()
    main = label or name.title() or "Gift"
    secondary = ""
    if category and category.strip().lower() != main.strip().lower():
        secondary = category.strip()
    return {"main": main, "secondary": secondary}
