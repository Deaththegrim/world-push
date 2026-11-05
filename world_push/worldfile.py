"""Reading a world file, Voyage's two layouts, and comparing worlds field by field."""
import json
from pathlib import Path

PARTY_SECTIONS = ("quests", "questTriggers", "arcs", "narrativeEvents")
KNOWN_SECTIONS = ("factions", "locations", "npcs", "realms", "regions")
VOYAGE_OWN = ("compatibilityRevision",)                            # Voyage bumps this itself on save; its change is nobody's edit
KEEP_IF_ABSENT = ("compatibilityRevision", "characterCreationMusic")   # a file without them keeps Studio's
GENERATED = "__generated_quest_progress__/"                        # triggers Voyage builds on save


class WorldFileError(Exception):
    pass


def _no_duplicates(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise WorldFileError(f'This file has "{k}" twice in the same place. JSON keeps only the last one, so the other would be lost. Rename or remove one.')
        out[k] = v
    return out


def read_file(path):
    """(the world JSON in a file, the world id it says it came from or None): a Studio export, a patch file, this app's backup, or an
    API envelope around one"""
    try:
        d = json.loads(Path(path).read_bytes().decode("utf-8-sig"), object_pairs_hook=_no_duplicates)
    except UnicodeDecodeError as e:
        raise WorldFileError(f"This file isn't UTF-8 text ({e.reason}).") from e
    except json.JSONDecodeError as e:
        raise WorldFileError(f"This file isn't valid JSON: line {e.lineno}, column {e.colno}: {e.msg}. "
                             "That usually means a missing comma or quote near there.") from e
    source = None
    for _ in range(3):
        if not isinstance(d, dict) or "heroesVersion" in d:
            break
        source = d.get("shortId") or source
        if "initialGameState" in d:
            d = d["initialGameState"]
            break
        if isinstance(d.get("world"), dict):
            d = d["world"]
        elif isinstance(d.get("data"), dict):
            d = d["data"]
        else:
            break
    if not isinstance(d, dict) or "heroesVersion" not in d:
        raise WorldFileError("This JSON isn't a whole Voyage world (it has no heroesVersion). Export the world from Studio's "
                             "JSON editor; a piece of a world can't be pushed, because a push replaces the whole draft.")
    try:
        json.dumps(d, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError as e:
        raise WorldFileError("This file has a broken character in it, usually half of an emoji cut off by an edit. "
                             "Look for an escape like \\ud83d with nothing after it.") from e
    return d, source


def read_state(path):
    return read_file(path)[0]


def fold(state):
    """one layout for comparing and sending: `triggers`, the party sections at the top level, `known`, `initialRelationship`"""
    out = json.loads(json.dumps(state))
    if "triggerDefinitions" in out:
        if "triggers" in out:
            raise WorldFileError("This world holds both triggers and triggerDefinitions; keep one.")
        out["triggers"] = out.pop("triggerDefinitions")
    parties = out.pop("parties", None)
    if parties is not None:
        if set(parties) - {""} or set(parties.get("", {})) - set(PARTY_SECTIONS):
            raise WorldFileError("This world's parties section has a shape this app doesn't know; nothing was sent.")
        for k, v in parties.get("", {}).items():
            if k in out:
                raise WorldFileError(f"This world holds {k} both at the top level and under parties; keep one.")
            out[k] = v
    for section in KNOWN_SECTIONS:
        for key, rec in (out.get(section) or {}).items():
            if isinstance(rec, dict) and "initialKnown" in rec:
                if "known" in rec:
                    raise WorldFileError(f"{section} > {key} holds both known and initialKnown; keep one.")
                rec["known"] = rec.pop("initialKnown")
    for key, rec in (out.get("npcs") or {}).items():
        if isinstance(rec, dict) and "relationship" in rec:
            if "initialRelationship" in rec:
                raise WorldFileError(f"npcs > {key} holds both relationship and initialRelationship; keep one.")
            rec["initialRelationship"] = rec.pop("relationship")
    qt = out.get("questTriggers")
    if isinstance(qt, dict):
        out["questTriggers"] = {k: v for k, v in qt.items() if not k.startswith(GENERATED)}
    return out


def authored(state):
    return {k: v for k, v in state.items() if k not in VOYAGE_OWN}


def _same(x, y):
    return x == y   # Python: 1 == 1.0, which is the only spelling Voyage changes


def diff(old, new):
    """[(kind, path as a list, old value, new value)] from old to new; kind is added, removed or changed"""
    out = []

    def walk(x, y, path):
        if isinstance(x, dict) and isinstance(y, dict):
            for k in sorted(x.keys() | y.keys(), key=str):
                if k not in x:
                    out.append(("added", path + [k], None, y[k]))
                elif k not in y:
                    out.append(("removed", path + [k], x[k], None))
                else:
                    walk(x[k], y[k], path + [k])
        elif not _same(x, y):
            out.append(("changed", path, x, y))

    walk(old, new, [])
    return out


EMPTY = ({}, [], None, "")


def lost_on_save(sent, stored):
    """what Voyage did not keep of what was sent: a field it dropped or changed. Fields it added on its own save don't count, and an
    empty value sent and stored empty or left out is the same thing."""
    return [d for d in diff(sent, stored) if d[0] != "added" and not (d[2] in EMPTY and d[3] in EMPTY)]


FILLED = {("characterCreationSettings", "premadeCustomizationEnabled"), ("itemSettings", "tierGenerationEnabled"),
          ("itemSettings", "imageGenerationEnabled"), ("itemSettings", "tiers")}
EMPTY_TASKS = {"generateItemGenerationAndUsage", "generateFactionDetails", "custom"}


def voyage_refills(kind, path, old, new):
    """a field the live draft has and the file doesn't, which Voyage writes back on any save, so it isn't really going away"""
    if old in EMPTY and new in EMPTY:
        return True
    if kind != "removed":
        return False
    if tuple(path) in FILLED:
        return True
    if len(path) == 2 and path[0] == "aiInstructions" and path[1] in EMPTY_TASKS and old in EMPTY:
        return True
    return len(path) == 3 and path[0] == "npcs" and path[2] == "detailType" and old == "detailed"


def real_changes(old, new):
    return [d for d in diff(old, new) if not voyage_refills(*d)]
