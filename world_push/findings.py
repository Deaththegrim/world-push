"""What's wrong and how to fix it. Voyage's errors and warnings grouped by type, each with plain advice. Display only: nothing here
changes a world. A type with no rule below still shows Voyage's own message; it is never hidden."""
import re
from dataclasses import dataclass, field

DIALOGUE_ONLY = {"generateDialogue": "Style, Tone, and Length", "generateNpcChatSummary": "Summary Guidance",
                 "generateConversationStarters": "Conversation Starter Guidance"}
PREVIEW_CAP_NOTE = "Voyage allows 1.5x this while it's a draft, but you can't publish until it's under."
DRAFT_CAP_NOTE = "A draft may run to 1.5x the publish limit. Getting under the draft limit lets you save; you can't publish until it's under the publish limit too."


@dataclass
class Finding:
    severity: str          # error (Voyage refuses a save), publish (can save, can't publish) or warning
    title: str
    wrong: str
    fix: str
    items: list = field(default_factory=list)   # (where, Voyage's message)


RULES = [
    (r"game-state\.limit\.npc\b", "NPC over the size limit", "This NPC record is too long. The limit counts the whole record.",
     "Shorten it, or move background notes (routine, tastes, history) into a worldLore entry. Lore goes to the narrator too and "
     "players don't see it. Start the entry with the NPC's name so the narrator knows who it's about."),
    (r"game-state\.limit\.story-start\b", "Story start over the size limit", "This story start is too long. The limit counts the whole start.",
     "Cut repeated rules from its questGenerationGuidance, or move long rules to a worldLore entry or aiInstructions."),
    (r"game-state\.limit\.ai-instruction\b", "AI instruction over the size limit", "One instruction entry is too long.",
     "Split it into separately named keys under the same task; Voyage adds extra keys on. The exceptions are generateDialogue, "
     "generateConversationStarters and generateNpcChatSummary, which keep only their named section and custom."),
    (r"game-state\.limit\.", "Over a size limit", "This field or section is longer than Voyage allows.",
     "Shorten it, or move some of the text somewhere else the narrator reads. Voyage's message names the limit and how far over it is."),
    (r"schema\.unknown-field.*'(rewardXp|rewardYen)'", "Quest reward fields Voyage ignores", "rewardXp and rewardYen aren't Voyage fields, so these numbers do nothing in play.",
     "Safe to leave. To clear the warning, delete those fields. To really pay a reward, use a player-experience or item-add effect in the quest's onCompleteEffects."),
    (r"schema\.unknown-field", "Fields Voyage ignores", "Voyage doesn't know this field, so it has no effect in play.",
     "Safe to leave. To clear the warning, delete the field, or check its spelling if you meant a real one."),
    (r"invalid-reference.*Invalid type .* at npcs", "NPC type that doesn't exist", "This NPC's type isn't in your npcTypes list.",
     "Add that name to npcTypes, or change the NPC's type to one from the list in Voyage's message."),
    (r"invalid-reference.*currentArea is blank", "NPC with no area", "This NPC's location has areas, but no area is set, so they can turn up anywhere in that location.",
     "Fine if that's what you want. Otherwise set currentArea to one of the areas in Voyage's message."),
    (r"invalid-reference", "Reference to something that doesn't exist", "This field names a record the world doesn't have.",
     "Fix the name to match an existing record, or add the missing record. Voyage's message lists the allowed names."),
    (r"schema\.", "Field in the wrong shape", "This field doesn't match what Voyage expects.", "Compare it with the same field on a record that works."),
]


def _rule(code, message):
    text = f"{code} {message}"
    for pattern, title, wrong, fix in RULES:
        if re.search(pattern, text):
            return title, wrong, fix
    return code or "Other", "Voyage flagged this. This app has no extra advice for this type yet.", "Follow Voyage's message below."


def _template(message):
    return re.sub(r'"[^"]*"', '"…"', re.sub(r"\d[\d,]*", "#", message))[:80]


def group(draft, publish, local=()):
    """the findings, worst first. An error at draft blocks a save; one only at publish means it can be saved but not published."""
    groups = {}

    def add(severity, issue, at_publish=None):
        code, message, path = issue.get("code") or "", issue.get("message") or "", issue.get("path") or ""
        title, wrong, fix = _rule(code, message)
        if ".limit." in code and severity != "warning":
            fix = f"{fix} {PREVIEW_CAP_NOTE if severity == 'publish' else DRAFT_CAP_NOTE}"
        if at_publish and at_publish != message:
            message = f"{message}. To publish: {at_publish}" if message else at_publish
        f = groups.setdefault((severity, title, wrong), Finding(severity, title, wrong, fix))
        f.items.append((path, message))

    def key(i):
        return i.get("code"), i.get("path")

    shown = {(key(i), i.get("message")) for i in draft.get("errors") or []}
    publish_says = {}
    for i in publish.get("errors") or []:
        publish_says.setdefault(key(i), []).append(i.get("message"))
    drafted = [key(i) for i in draft.get("errors") or []]

    def size_at_publish(i):
        """a size limit's other number. Two errors on one place can't be paired, so each keeps its own words."""
        said = publish_says.get(key(i), [])
        return said[0] if ".limit." in (i.get("code") or "") and len(said) == 1 and drafted.count(key(i)) == 1 else None

    for i in draft.get("errors") or []:
        paired = size_at_publish(i)
        add("error", i, paired)
        shown.add((key(i), paired))
    for i in publish.get("errors") or []:
        if (key(i), i.get("message")) not in shown:
            add("publish", i)
    seen = set()
    for i in (draft.get("warnings") or []) + (publish.get("warnings") or []):
        if (key(i), i.get("message")) not in seen:
            seen.add((key(i), i.get("message")))
            add("warning", i)
    order = {"error": 0, "publish": 1, "warning": 2}
    found = sorted(groups.values(), key=lambda f: (order[f.severity], -len(f.items)))
    return [f for f in local if f.severity == "error"] + found + [f for f in local if f.severity != "error"]


def local_checks(state):
    """problems Voyage's check passes but play or a save won't: found by hand when a real patch hit them"""
    found = []
    tasks = state.get("aiInstructions") or {}
    dropped = []
    for task, named in DIALOGUE_ONLY.items():
        for k in tasks.get(task) or {}:
            if k not in ("custom", named):
                dropped.append((f"aiInstructions > {task} > {k}", f"Voyage drops this key on save: {task} keeps only {named} and custom."))
    if dropped:
        found.append(Finding("warning", "Instructions Voyage will throw away on save",
                             "These tasks keep only their named section and custom, so the text in other keys disappears when the world is saved.",
                             "Move the text into that task's custom key.", dropped))
    voices = state.get("worldVoices") or {}
    missing = [(f"npcs > {k} > worldVoiceId", f"{k} names the world voice {rec['worldVoiceId']!r}, which doesn't exist.")
               for k, rec in (state.get("npcs") or {}).items() if isinstance(rec, dict) and rec.get("worldVoiceId") and rec["worldVoiceId"] not in voices]
    if missing:
        found.append(Finding("warning", "NPC voice that doesn't exist", "These NPCs point at a world voice the world doesn't have, so they speak with a fallback voice.",
                             "Add that voice to worldVoices, or remove worldVoiceId from the NPC.", missing))
    return found
