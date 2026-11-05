"""Voyage's messages and paths in plain words, for people who have never read the world JSON. Display only."""
import re

PLACES = {"npcs": "NPC", "npcTypes": "NPC type", "storyStarts": "Story start", "locations": "Location", "regions": "Region", "realms": "Realm",
          "factions": "Faction", "traits": "Trait", "traitCategories": "Creator page", "abilities": "Ability", "skills": "Skill", "quests": "Quest",
          "questTriggers": "Quest trigger", "triggers": "Trigger", "narrativeEvents": "Story event", "worldLore": "Lore entry", "itemTypes": "Item",
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
