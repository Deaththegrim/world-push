"""What's wrong and how to fix it. Voyage's errors and warnings grouped by type, each with plain advice. Display only: nothing here
changes a world. A type with no rule below still shows Voyage's own message; it is never hidden."""
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field

DIALOGUE_ONLY = {"generateDialogue": "Style, Tone, and Length", "generateNpcChatSummary": "Summary Guidance",
                 "generateConversationStarters": "Conversation Starter Guidance"}
PREVIEW_CAP_NOTE = "Drafts have a higher limit, so you can keep saving it, but it has to be under this limit to publish."
DRAFT_CAP_NOTE = "Drafts have higher limits than published worlds, so there are two limits: one to save, and a lower one to publish."


@dataclass
class Finding:
    severity: str          # error (Voyage refuses a save), publish (can save, can't publish) or warning
    title: str
    wrong: str
    fix: str
    items: list = field(default_factory=list)   # (where, Voyage's message)


RULES = [
    (r"game-state\.limit\.npc\b", "NPC over the size limit", "This NPC record is too long. The limit counts the whole record.",
     "Shorten it, or move background notes (routine, tastes, history) into a worldLore entry. Lore goes to the narrator too. "
     "Start the entry with the NPC's name so the narrator knows who it's about."),
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
    (r"invalid-reference.*(?:triggers|triggerDefinitions|questTriggers)\..+? references missing (?:quests|objectives)", "Trigger pointing at a quest or objective that doesn't exist",
     "This trigger starts, completes or reveals a quest or objective the world doesn't have, so that step does nothing in play. "
     "It's a usual reason a quest objective never ticks.",
     "Match the questId to the quest's exact name, and the objectiveId to an id inside that quest's objectives. Voyage's message "
     "names the one it couldn't find."),
    (r"invalid-reference.*(?:triggers|triggerDefinitions|questTriggers)\..+? references missing (?:areas|locations|regions|realms)",
     "Trigger watching a place that doesn't exist",
     "This trigger's condition names a place (a location, area, region or realm) the world doesn't have by that exact name. With an "
     "equals condition, the trigger never fires there.",
     "Fix the spelling, or add the place. If the condition is a contains match on purpose, so part of a name is enough, it still works "
     "in play and this warning can be left."),
    (r"invalid-choice.*Slot \"[^\"]*\" is for category", "Item in a slot meant for another category",
     "This item's slot only takes items of the category Voyage names, and the item has a different category.",
     "Change the item's category to the one Voyage names, or set its slot to one made for its own category."),
    (r"invalid-choice", "Value that isn't one of the choices", "This field has to be one of a set list of values, and it isn't.",
     "Change it to one of the values Voyage lists in its message, or add the value to that list if the list is yours."),
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


SEMANTIC_CAP = 500           # Voyage's publish limit, on triggers and again on questTriggers (drafts allow 1.5x)
SEMANTIC = ("story", "action")   # a condition the AI judges each turn, rather than a fact the game checks


def _dict(x):
    """a section as Voyage would read it; a malformed one is Voyage's to report, and never stops these checks"""
    return x if isinstance(x, dict) else {}


def _list(x):
    return x if isinstance(x, list) else []


def _semantic(t):
    return isinstance(t, dict) and any(isinstance(c, dict) and c.get("type") in SEMANTIC for c in _list(t.get("conditions")))


def built_quest_checks(state):
    """questTriggers Voyage builds on save, one per detailed quest (no detailType counts as detailed) whose completion is a story
    condition with a query that isn't blank. A file without them passes
    Voyage's check, and the stored draft then can't publish (seen 2026-10-27: 458 sent, 835 stored)"""
    return sum(1 for q in _dict(state.get("quests")).values() if isinstance(q, dict) and q.get("detailType", "detailed") == "detailed"
               and isinstance(q.get("completionCondition"), dict) and q["completionCondition"].get("type") == "story"
               and isinstance(q["completionCondition"].get("query"), str) and q["completionCondition"]["query"].strip())


def budgets(state):
    """(AI-judged triggers, AI-judged quest triggers as stored after a save, how many of those Voyage builds itself)"""
    built = built_quest_checks(state)
    return (sum(1 for t in _dict(state.get("triggers")).values() if _semantic(t)),
            sum(1 for t in _dict(state.get("questTriggers")).values() if _semantic(t)) + built, built)


def _same_trigger(t):
    """what a trigger does, ignoring its name and the order of its conditions"""
    conds = sorted(json.dumps(c, sort_keys=True) for c in _list(t.get("conditions")))
    rest = {k: v for k, v in t.items() if k not in ("name", "conditions")}
    return json.dumps(conds), json.dumps(rest, sort_keys=True)


def _others(n, names, most=4):
    rest = [m for m in names if m != n]
    return ", ".join(rest[:most]) + (f" and {len(rest) - most:,} more" if len(rest) > most else "")


def duplicate_triggers(state):
    """triggers that are the same, or ask the AI the same question, across triggers and questTriggers"""
    whens, sames, semantic_when = {}, {}, {}
    for sec, label in (("triggers", "Trigger"), ("questTriggers", "Quest trigger")):
        for k, t in _dict(state.get(sec)).items():
            if isinstance(t, dict) and _list(t.get("conditions")):
                when, rest = _same_trigger(t)
                whens.setdefault(when, []).append(f"{label}: {k}")
                semantic_when[when] = _semantic(t)
                sames.setdefault((when, rest), []).append(f"{label}: {k}")
    found = []
    copies = [names for names in sames.values() if len(names) > 1]
    if copies:
        found.append(Finding("warning", "The same trigger more than once", "These triggers have the same conditions and do the same things, "
                             "so whatever they do happens twice, and each AI-judged one counts against the limit of 500 again.",
                             "Keep one and delete the others.", [(n, "Same as " + _others(n, names)) for names in copies for n in names]))
    kinds = Counter(when for when, _rest in sames)   # how many different things are done on each set of conditions
    shared = [names for when, names in whens.items() if kinds[when] > 1 and semantic_when.get(when)]
    if shared:   # mechanical twins are normal (one condition split across triggers for room); a repeated AI question is not
        found.append(Finding("warning", "The same AI-judged question asked more than once", "These triggers have the same conditions, "
                             "including one the AI judges, so the AI is asked the same question once for each of them every turn it's checked. "
                             "Each one counts against the limit of 500 AI-judged triggers, and against the checks Voyage runs each turn.",
                             "Fine if they really need to stay apart. Otherwise merge their effects into one trigger.",
                             [(n, "Same conditions as " + _others(n, names)) for names in shared for n in names]))
    return found


def local_checks(state):
    """problems Voyage's check passes but play or a save won't: found by hand when a real patch hit them"""
    found = []
    tasks = _dict(state.get("aiInstructions"))
    dropped = []
    for task, named in DIALOGUE_ONLY.items():
        for k in _dict(tasks.get(task)):
            if k not in ("custom", named):
                dropped.append((f"aiInstructions > {task} > {k}", f"Voyage drops this key on save: {task} keeps only {named} and custom."))
    if dropped:
        found.append(Finding("warning", "Instructions Voyage will throw away on save",
                             "These tasks keep only their named section and custom, so the text in other keys disappears when the world is saved.",
                             "Move the text into that task's custom key.", dropped))
    voices = _dict(state.get("worldVoices"))
    missing = [(f"npcs > {k} > worldVoiceId", f"{k} names the world voice {rec['worldVoiceId']!r}, which doesn't exist.")
               for k, rec in _dict(state.get("npcs")).items() if isinstance(rec, dict) and isinstance(rec.get("worldVoiceId"), str)
               and rec["worldVoiceId"] and rec["worldVoiceId"] not in voices]
    if missing:
        found.append(Finding("warning", "NPC voice that doesn't exist", "These NPCs point at a world voice the world doesn't have, so they speak with a fallback voice.",
                             "Add that voice to worldVoices, or remove worldVoiceId from the NPC.", missing))
    sem, qsem, built = budgets(state)
    if qsem > SEMANTIC_CAP and built:
        found.append(Finding("publish", "Too many AI-judged quest checks once saved",
                             f"Each detailed quest that completes on a story condition gets an AI-judged check Voyage builds on save. With your "
                             f"{qsem - built:,} AI-judged quest triggers, that makes {qsem:,}, over the limit of {SEMANTIC_CAP:,}. Voyage's check can't see this "
                             "yet, so the push works and publishing fails afterwards.",
                             "Complete some quests through objectives or a trigger instead of a story completionCondition, or remove some "
                             "AI-judged quest triggers.", [("quests", f"{built:,} quests complete on a story condition")]))
    return found + duplicate_triggers(state)


_PORTRAIT = ("portraitUrl", "portraitFocusX", "portraitFocusY", "portraitZoom")


def _premade_key(p):
    """a premade's name, or for one with no name a short print of its content, so moving it in the list changes nothing"""
    if p.get("name"):
        return str(p["name"])
    return "(no name: " + hashlib.sha1(json.dumps(p, sort_keys=True).encode()).hexdigest()[:6] + ")"


def _premades(state):
    """[(key, record)] of a world's premade characters, in list order; two with one name are both kept"""
    rows = _list(state.get("premadeCharacters")) if isinstance(state, dict) else []
    return [(_premade_key(p), p) for p in rows if isinstance(p, dict)]


def _short(have, mine):
    """{key: how many fewer} where `mine` has fewer of a premade than `have`"""
    a, b = Counter(k for k, _ in have), Counter(k for k, _ in mine)
    return {k: n - b[k] for k, n in a.items() if n > b[k]}


def _how_many(n, missing):
    return "" if n == missing else f" ({missing:,} of the {n:,} with this name)"


def premade_checks(live, ours, last_push=None):
    """premades a push would take away, ones Studio lost since the last push, and ones overwritten to read the same. Studio has wiped or
    overwritten premades when one is added or edited (bug VOY-2803, reported twice on Voyage's Discord in October 2026). Counted by name,
    so two premades sharing a name can't hide one being lost."""
    found = []
    have, mine = _premades(live), _premades(ours)
    counts_live = Counter(k for k, _ in have)
    gone = _short(have, mine)
    if gone:
        found.append(Finding("warning", "This push removes premade characters", "The live draft has premade characters your file doesn't, so a push "
                             "deletes them.", "If you meant to keep them, export a fresh copy from Studio and make your edits in that, or add "
                             "them back to your file.", [(f"Premade character: {k}", "In the live draft, not in your file" + _how_many(counts_live[k], n) + ".")
                                                         for k, n in gone.items()]))
    if last_push is not None:
        before = _premades(last_push)
        lost = _short(before, have)
        if lost:
            counts_before, counts_mine = Counter(k for k, _ in before), Counter(k for k, _ in mine)
            found.append(Finding("warning", "Premade characters missing from the live draft", "These premades were in your last push from this app "
                                 "and the live draft no longer has them. Studio has wiped premades when one was added or edited (Voyage bug "
                                 "VOY-2803), so check this was you.", "Pushing your file puts back the ones it has. Any it doesn't have are in "
                                 "your backups folder, in the backup from before your last push.",
                                 [(f"Premade character: {k}", ("Your file has it, so a push puts it back." if counts_mine[k] >= counts_before[k] else
                                                               "Your file doesn't have it either.") + _how_many(counts_before[k], n))
                                  for k, n in lost.items()]))
    texts = {}
    for k, p in mine:
        body = json.dumps({f: v for f, v in p.items() if f not in ("name",) + _PORTRAIT}, sort_keys=True)
        if len(body) > 40:
            texts.setdefault(body, []).append(k)
    same = [names for names in texts.values() if len(set(names)) > 1]
    if same:
        found.append(Finding("warning", "Premade characters that read exactly the same", "These premades have different names but the same "
                             "description, traits and backstory. Studio has overwritten premades with one character's text (Voyage bug "
                             "VOY-2803).", "If that wasn't on purpose, put each one's own text back from an older copy or a backup.",
                             [(f"Premade character: {n}", "Same as " + _others(n, names)) for names in same for n in dict.fromkeys(names)]))
    return found


ENDINGS = {"win-game": "ends the game as a win", "lose-game": "ends the game as a loss", "end-game": "ends the game"}   # Voyage's three


def _endings(state):
    """Counter of (place, what it does) for every effect that ends a game: win-game, lose-game or end-game (the endGame section is only
    the closing words). Counted, so a second ending in the same record, or one widened to everyone, reads as new."""
    out = Counter()
    labels = {"triggers": "Trigger", "questTriggers": "Quest trigger", "quests": "Quest", "narrativeEvents": "Story event"}

    def walk(x, place):
        if isinstance(x, dict):
            if x.get("type") in ENDINGS:
                scope = "everyone" if x.get("endScope", "game") == "game" else "the players who meet it"
                out[(place, f"{ENDINGS[x['type']]} for {scope}" + (f"; the others have {x['othersOutcome']}" if x.get("othersOutcome") else ""))] += 1
            for v in x.values():
                walk(v, place)
        elif isinstance(x, list):
            for v in x:
                walk(v, place)

    for sec, label in labels.items():
        for k, rec in _dict(state.get(sec) if isinstance(state, dict) else None).items():
            walk(rec, f"{label}: {k}")
    return out


def ending_checks(live, ours, last_push=None):
    """a way for the game to end that Studio added since the last push, or that this push adds. Studio's assistant has added an ending to
    a world meant to be endless without saying so (Voyage's Discord, 2026-10-18)."""
    found = []
    have, mine = _endings(live), _endings(ours)
    if last_push is not None:
        added = have - _endings(last_push)
        if added:
            found.append(Finding("warning", "Studio added a way for the game to end", "Since your last push from this app, the live draft gained "
                                 "an effect that ends a player's game when it fires (a win, a loss or a plain ending). Studio's assistant has "
                                 "added these without saying so.", "If your world is meant to be endless, make sure your file doesn't have it "
                                 "either; a push replaces the draft with your file.",
                                 [(p, d + (". Your file has it too." if mine[(p, d)] >= have[(p, d)] else ". Your file doesn't."))
                                  for (p, d) in added]))
    new = mine - have
    if new:
        found.append(Finding("warning", "This push adds a way for the game to end", "Your file has effects that end the game which the live draft "
                             "doesn't. When one fires, the game ends.", "Fine if your world is meant to end there. If it's meant to be endless, "
                             "remove them.", [(p, d) for (p, d) in new]))
    return found
