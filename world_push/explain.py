"""Voyage's messages and paths in plain words, for people who have never read the world JSON. Display only."""
import re

PLACES = {"npcs": "NPC", "npcTypes": "NPC type", "storyStarts": "Story start", "locations": "Location", "regions": "Region", "realms": "Realm",
          "factions": "Faction", "traits": "Trait", "traitCategories": "Creator page", "abilities": "Ability", "skills": "Skill", "quests": "Quest",
          "questTriggers": "Quest trigger", "triggers": "Trigger", "triggerDefinitions": "Trigger", "narrativeEvents": "Story event", "worldLore": "Lore entry", "itemTypes": "Item",
          "aiInstructions": "Narrator instructions", "premadeCharacters": "Premade character", "gameModes": "Game mode"}
PLACE = re.compile(r'(\w+)(?:\.([^.\[]+)|\["((?:[^"\\]|\\.)*)"\])(.*)')
OVER = re.compile(r"exceeds the ([\d,]+) character limit by ([\d,]+) character")
MEANS = {"error": "Voyage won't save your file until this is fixed.",
         "publish": "This one won't stop a save, but you can't publish until it's fixed.",
         "warning": "This won't stop you saving or publishing. It's worth a look."}
HELP = """
<h3>Draft and publish</h3>
<p>Your <b>draft</b> is your working copy in Studio. Players don't see it. <b>Publishing</b> is what puts it in front of players. This app only ever changes the draft, and you publish from Studio yourself.</p>
<p>Voyage checks both. Drafts have higher limits than published worlds, so a file can be fine as a draft and still too big to publish. An NPC card, for example, can run to 12,000 characters in a draft, but it has to be 8,000 or under to publish.</p>
<h3>"Draft" on a world you've published</h3>
<p>That's normal. Once a world is published, Studio shows you its draft: your working copy. You can change the draft as much as you like and players won't see it. When you publish from Studio again, the draft becomes the published world. Creators on Voyage's Discord report that games players already started stay on the version they started with, and new games get the new one.</p>
<p>So a push from this app changes only your draft. Nothing reaches players until you publish in Studio.</p>
<h3>Where's the API key?</h3>
<p>It isn't in your account settings. In Studio, open any one of your worlds, then that world's Settings, then API keys. One key works for every world your account owns.</p>
<h3>What the labels mean</h3>
<p><b>Blocks saving (red):</b> Voyage won't take the file until it's fixed.<br>
<b>Blocks publishing (orange):</b> this one won't stop a save, but you can't publish until it's fixed.<br>
<b>Warning (grey):</b> nothing is stopped. Read it and decide.</p>
<h3>How characters are counted</h3>
<p>A character is any letter, number, space or punctuation mark. Some limits count one piece of text. Others, like an NPC card, count the whole record as it sits in your JSON file, field names included. That's why a card can go over when its text looks short enough.</p>
<p>Voyage's count won't always match what you measure in your file. It skips some empty fields, and limits on narrator instructions also count Voyage's own built-in text. Go by the numbers Voyage gives. An emoji can use up 2 characters.</p>
<h3>Words you'll see</h3>
<p><b>JSON file:</b> the file holding your whole world, the one you export from Studio's editor.<br>
<b>NPC card or record:</b> everything saved about one NPC.<br>
<b>worldLore:</b> background notes for the narrator.<br>
<b>aiInstructions:</b> the rules you give the narrator.<br>
<b>Voyage says:</b> Voyage's own words, copied as they came. Search for them if you need help.</p>
<h3>Backups and Studio edits</h3>
<p>Before each push, the draft as it stood is saved to your backups folder. To go back, open that backup in this app and push it.</p>
<p><b>Edits made in Studio</b> lists what changed in Studio since your last push from this app. Pushing replaces those edits, so copy anything you want to keep into your file first.</p>
<p>The first time this computer pushes a world, the app has no record to compare against, so it asks you to type the world's title. Look at the What changes tab first.</p>
"""


def plain_place(path):
    """$.npcs["Ann Lee"].type -> NPC: Ann Lee (type). Quests sit under parties[""]. A shape or section this doesn't know stays as Voyage
    wrote it, without the $."""
    rest = (path or "").removeprefix("$.").removeprefix('parties[""].')
    m = PLACE.match(rest)
    label = PLACES.get(m.group(1)) if m else None
    if not label:
        return rest
    inside = m.group(4).removeprefix(".")
    return f"{label}: {m.group(2) or m.group(3)}" + (f" ({inside})" if inside else "")


def _number(text):
    return int(text.replace(",", ""))


def _chars(n):
    return f"{n:,} character" + ("" if n == 1 else "s")


def plain_size(message, severity):
    """how long it is and how much to cut, from Voyage's own numbers. None when the message states no character limit."""
    found = [(_number(a), _number(b)) for a, b in OVER.findall(message or "")]
    if not found:
        return None
    limit, over = found[0]
    size = f"This is {limit + over:,} characters."
    if len(found) > 1:
        return f"{size} Cut {_chars(over)} to save it as a draft (limit {limit:,}). Cut {_chars(found[1][1])} to publish it (limit {found[1][0]:,})."
    if severity == "publish":
        return f"{size} Cut {_chars(over)} to publish it (limit {limit:,})."
    if severity == "warning":
        return f"{size} The limit is {limit:,}."
    return f"{size} Cut {_chars(over)} to save it (limit {limit:,})."


SEVERITY_WORDS = {"error": "Blocks saving", "publish": "Blocks publishing", "warning": "Warning"}


def matches(finding, severity, words):
    """the places in a finding that pass the filter: all of them when the problem's own title or advice holds the words"""
    if severity and finding.severity != severity:
        return []
    words = (words or "").strip().lower()
    if not words or words in f"{finding.title} {finding.wrong} {finding.fix}".lower():
        return list(finding.items)
    return [(where, said) for where, said in finding.items if words in f"{plain_place(where)} {where} {said}".lower()]


def report(c, file_name, version, when):
    """the whole check as plain text, to paste to someone helping"""
    lines = [f"World Push {version} check, {when}", f"World: {c.title} [{c.short_id}]", f"File: {file_name}",
             f"Save as a draft: {'yes' if not c.blocked and c.draft.get('valid') else 'no'}. Publish: {'yes' if c.can_publish else 'no'}.",
             f"Changes from the live draft: {len(c.changes):,}. Edits made in Studio since the last push: {len(c.studio_edits):,}."]
    lines += [f"Can't push: {b}" for b in c.blocked] + [f"Note: {n}" for n in c.notes]
    if c.changes:
        lines += ["", "What a push changes:"] + [f"  {line}" for line in summarize(c.changes)]
    if not c.findings:
        lines.append("\nVoyage found nothing to report.")
    for f in c.findings:
        lines += ["", f"{SEVERITY_WORDS[f.severity]}: {f.title} ({len(f.items):,})", f"  What's wrong: {f.wrong}", f"  How to fix it: {f.fix}"]
        for where, said in f.items:
            size = plain_size(said, f.severity)
            lines.append(f"  - {plain_place(where)}: {said}" + (f" ({size})" if size else ""))
    return "\n".join(lines) + "\n"


def summarize(changes, most=6):
    """what a push changes, by record: "Abilities: 59 added (Iron Fist, ...)", from the field changes"""
    sections = {}
    for kind, path, _old, _new in changes:
        if not path:
            continue
        sec = sections.setdefault(str(path[0]), {"added": {}, "removed": {}, "changed": {}, "fields": 0})
        if len(path) == 1:
            sec["fields"] += 1
        elif len(path) == 2 and kind in ("added", "removed"):
            sec[kind][str(path[1])] = None
        else:
            sec["changed"][str(path[1])] = None
    lines = []
    for name, sec in sorted(sections.items(), key=lambda kv: -sum(len(kv[1][k]) for k in ("added", "removed", "changed"))):
        label = PLACES.get(name)
        label = name if not label else label if label.endswith("s") else label[:-1] + "ies" if label.endswith("y") else label + "s"
        parts = []
        for kind in ("added", "removed", "changed"):
            names = [n for n in sec[kind] if kind != "changed" or (n not in sec["added"] and n not in sec["removed"])]
            if names:
                shown = ", ".join(names[:most]) + (f" and {len(names) - most:,} more" if len(names) > most else "")
                parts.append(f"{len(names):,} {kind} ({shown})")
        if sec["fields"]:
            parts.append("changed" if not parts else "the section itself changed")
        lines.append(f"{label}: " + "; ".join(parts))
    return lines
