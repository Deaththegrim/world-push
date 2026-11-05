"""Reading a world file, Voyage's two layouts, and comparing worlds field by field."""
import json
from pathlib import Path

PARTY_SECTIONS = ("quests", "questTriggers", "arcs", "narrativeEvents")
KNOWN_SECTIONS = ("factions", "locations", "npcs", "realms", "regions")
VOYAGE_OWN = ("compatibilityRevision", "characterCreationMusic")   # Voyage writes these itself; their change is nobody's edit
GENERATED = "__generated_quest_progress__/"                        # triggers Voyage builds on save


class WorldFileError(Exception):
    pass


def read_state(path):
    """the world JSON in a file: a Studio export, a patch file, this app's backup, or an API envelope around one"""
    try:
        d = json.loads(Path(path).read_bytes().decode("utf-8-sig"))
    except UnicodeDecodeError as e:
        raise WorldFileError(f"This file isn't UTF-8 text ({e.reason}).") from e
    except json.JSONDecodeError as e:
        raise WorldFileError(f"This file isn't valid JSON: line {e.lineno}, column {e.colno}: {e.msg}. "
                             "That usually means a missing comma or quote near there.") from e
    for _ in range(3):
        if not isinstance(d, dict):
            break
        if "initialGameState" in d:
            d = d["initialGameState"]
            break
        if "world" in d:
            d = d["world"]
        elif isinstance(d.get("data"), dict):
            d = d["data"]
        else:
            break
    if not isinstance(d, dict) or "heroesVersion" not in d:
        raise WorldFileError("This JSON isn't a whole Voyage world (it has no heroesVersion). Export the world from Studio's "
                             "JSON editor; a piece of a world can't be pushed, because a push replaces the whole draft.")
    return d


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


def lost_on_save(sent, stored):
    """what Voyage did not keep of what was sent: a field it dropped or changed. Fields it added on its own save don't count, and an
    empty value sent and left out is the same thing."""
    return [d for d in diff(sent, stored) if d[0] != "added" and not (d[0] == "removed" and d[2] in ({}, [], None, ""))]
