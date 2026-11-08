"""Check (writes nothing to Voyage) and push (backup, conditional write, read back). No Qt here, so it can be tested and used alone."""
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .api import ApiError
from .findings import SEMANTIC_CAP, budgets, group, local_checks
from .worldfile import KEEP_IF_ABSENT, authored, fold, lost_on_save, read_file, real_changes

DATA_DIR = Path(os.environ.get("APPDATA") or os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "World Push"
BACKUP_DIR = Path.home() / "Documents" / "World Push backups"


def load_key(data_dir=DATA_DIR):
    f = data_dir / "key.txt"
    return f.read_text(encoding="utf-8").strip() if f.exists() else ""


def save_key(key, data_dir=DATA_DIR):
    """the key stays on this computer, readable by this user only (on Windows that's the user's own AppData folder)"""
    data_dir.mkdir(parents=True, exist_ok=True)
    f = data_dir / "key.txt"
    f.touch(mode=0o600, exist_ok=True)
    f.chmod(0o600)
    f.write_text(key.strip(), encoding="utf-8")


def load_settings(data_dir=None):
    """the last world and file, so the next start opens where this one left off; anything unreadable is a fresh start"""
    try:
        got = json.loads(((data_dir or DATA_DIR) / "settings.json").read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data_dir=None, **values):
    data_dir = data_dir or DATA_DIR   # read when called, so a test can point it elsewhere
    data_dir.mkdir(parents=True, exist_ok=True)
    _atomic(data_dir / "settings.json", json.dumps({**load_settings(data_dir), **values}, ensure_ascii=False))


def _atomic(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _baseline_file(data_dir, short_id):
    return data_dir / "baselines" / f"{short_id}.json"


def read_baseline(data_dir, short_id):
    f = _baseline_file(data_dir, short_id)
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    except (OSError, ValueError):   # unreadable counts as no record, and no record asks for the typed title
        return None


def write_baseline(data_dir, short_id, etag, state):
    f = _baseline_file(data_dir, short_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    _atomic(f, json.dumps({"etag": etag, "state": state}, ensure_ascii=False))


def backup(world, etag, backup_dir=None):
    """the live draft, saved and read back from disk before anything replaces it. A backup that can't be saved stops the push.
    To restore: open this file in the app and push it like any other."""
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", world.get("title") or "world").strip(" ._")[:60] or "world"
    folder = Path(backup_dir or BACKUP_DIR) / f"{safe} ({world['shortId']})"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{time.strftime('%Y-%m-%d %H-%M-%S')} before push.json"
    text = json.dumps({"etag": etag, "world": world}, ensure_ascii=False)
    _atomic(path, text)
    if path.read_text(encoding="utf-8") != text:
        raise OSError(f"the backup at {path} did not read back the same")
    return path


@dataclass
class Check:
    short_id: str
    title: str
    etag: str
    live: dict                 # the envelope as downloaded
    sending: dict              # the state a push would send
    draft: dict
    publish: dict
    findings: list
    changes: list              # live -> file
    studio_edits: list         # last push from this app -> live
    first_push: bool
    blocked: list = field(default_factory=list)   # why this can't be pushed
    notes: list = field(default_factory=list)

    @property
    def moved(self):
        return bool(self.studio_edits)

    @property
    def needs_title(self):
        """edits in Studio to replace, or no record of this world on this computer (a first push, another computer, a reinstall), which
        can't tell whether there are any"""
        return self.moved or self.first_push

    @property
    def can_publish(self):
        """Voyage's publish check, and nothing found here that stops a publish (the quest checks Voyage builds on save, say)"""
        return bool(self.publish.get("valid")) and not self.publish.get("errors") and not any(f.severity in ("error", "publish") for f in self.findings)


def check(client, path, short_id, data_dir=DATA_DIR):
    """everything worth knowing before a push. Downloads and asks Voyage to validate; changes nothing."""
    state, source = read_file(path)
    ours = fold(state)
    live, etag = client.download(short_id)
    live_state = fold(live["initialGameState"])
    notes, blocked = [], []
    if source and source != short_id:
        blocked.append(f"This file is a copy of a different world ({source}), not {short_id}. Pick that world, or if you really mean to, "
                       "push the bare world JSON from Studio's editor instead.")
    for k in KEEP_IF_ABSENT:
        if k in live_state and k not in ours:
            ours[k] = live_state[k]
    installed = live_state.get("mods") or []
    if installed and not ours.get("mods"):
        ours["mods"] = installed
        notes.append("Kept the mods installed in Studio: your file lists none, and sending it as it is would uninstall them.")
    if live.get("canSafelySave") is False or live.get("degradedReason"):
        blocked.append(f"Voyage says this world can't be saved safely right now ({live.get('degradedReason') or live.get('loadStatus')}). Open it in Studio first.")
    lv, ov = live_state.get("heroesVersion"), ours.get("heroesVersion")
    if lv != ov:
        blocked.append(f"Your file is world version {ov}, and the live draft is version {lv}. Export a fresh copy from Studio and make your edits in that.")
    revision = ours.get("compatibilityRevision")
    draft = client.validate(ours, "draft")
    publish = client.validate(ours, "publish")
    if ours.get("compatibilityRevision") != revision:
        notes.append(f"Lowered compatibilityRevision from {revision} to {ours['compatibilityRevision']}: Voyage's API only takes up to that number. It sets its own again on save.")
    if draft.get("errors") or not draft.get("valid"):
        blocked.append("Voyage would refuse to save this file. Fix the errors below first.")
    sem, qsem, built = budgets(ours)
    notes.append(f"AI-judged triggers: {sem:,} of {SEMANTIC_CAP:,} to publish. AI-judged quest checks once saved: {qsem:,} of {SEMANTIC_CAP:,}"
                 + (f" ({built:,} of them built by Voyage from quests that complete on a story condition)." if built else "."))
    base = read_baseline(data_dir, short_id)
    edits = []
    if base and base["etag"] != etag:
        edits = real_changes(authored(fold(base["state"])), authored(live_state))
    changes = real_changes(authored(live_state), authored(ours))
    if not changes:
        blocked.append("The live draft already holds this file. Nothing to push.")
        write_baseline(data_dir, short_id, etag, live_state)   # this is the state to notice Studio edits against from now on
    return Check(short_id, live.get("title") or short_id, etag, live, ours, draft, publish,
                 group(draft, publish, local_checks(ours)), changes, edits, base is None and bool(changes), blocked, notes)


@dataclass
class Pushed:
    etag: str
    backup: Path
    not_kept: list      # what Voyage changed or dropped of what was sent, as (kind, path, sent, stored)
    raced: bool = False  # someone else saved between the push and the read back


class PushStopped(Exception):
    """nothing was written, or the outcome is stated in the message"""


CLEAN_REFUSALS = {"studio_unavailable", "rate_limited", "request_in_progress", "too_large", "no_etag"}   # Voyage's guide: nothing was written


def push(client, c, typed_title=None, data_dir=DATA_DIR, backup_dir=None):
    if c.blocked:
        raise PushStopped(" ".join(c.blocked))
    if c.needs_title and (typed_title or "").strip() != c.title.strip():
        raise PushStopped("Type the world's exact title to confirm this push.")
    live, etag = client.download(c.short_id)
    if etag != c.etag:
        raise PushStopped("The draft changed in Studio after you pressed Check. Nothing was written. Press Check again.")
    try:
        saved = backup(live, etag, backup_dir)
    except (OSError, ValueError) as e:
        raise PushStopped(f"The backup couldn't be saved ({e}), so nothing was pushed.") from e
    world = {**live, "initialGameState": c.sending}   # title, image, tags, description and visibility stay Studio's
    try:
        new_etag = client.replace(world, etag)
    except ApiError as e:
        if e.status == 412:
            raise PushStopped("The draft changed in Studio during the push, so nothing was overwritten. Press Check again.") from e
        if e.code in CLEAN_REFUSALS or (e.status and e.status < 500 and e.code != "request_status_unknown"):
            raise PushStopped(f"Voyage refused the push, so nothing changed: {e}") from e
        raise PushStopped(f"Voyage didn't confirm the push ({e}). It may or may not have landed. Press Check to see what the draft holds. Your backup: {saved}") from e
    except Exception as e:   # the request went out and the answer is unknown, whatever broke
        raise PushStopped(f"The push was interrupted ({type(e).__name__}: {e}). It may or may not have landed. Press Check to see what the draft holds. Your backup: {saved}") from e
    try:
        back, back_etag = client.download(c.short_id)
        if new_etag and back_etag != new_etag:   # a save in Studio landed right behind ours: that edit is theirs, not the baseline
            write_baseline(data_dir, c.short_id, new_etag, c.sending)
            return Pushed(new_etag, saved, [], raced=True)
        stored = fold(back["initialGameState"])
        write_baseline(data_dir, c.short_id, back_etag or new_etag, stored)
        return Pushed(back_etag or new_etag, saved, lost_on_save(authored(c.sending), authored(stored)))
    except Exception as e:
        raise PushStopped(f"The push landed, but checking it afterwards failed ({type(e).__name__}: {e}). Press Check to confirm what the draft holds. Your backup: {saved}") from e
