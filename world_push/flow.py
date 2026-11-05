"""Check (writes nothing to Voyage) and push (backup, conditional write, read back). No Qt here, so it can be tested and used alone."""
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .api import ApiError
from .findings import group, local_checks
from .worldfile import VOYAGE_OWN, authored, diff, fold, lost_on_save, read_state

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


def _atomic(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _baseline_file(data_dir, short_id):
    return data_dir / "baselines" / f"{short_id}.json"


def read_baseline(data_dir, short_id):
    f = _baseline_file(data_dir, short_id)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def write_baseline(data_dir, short_id, etag, state):
    f = _baseline_file(data_dir, short_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    _atomic(f, json.dumps({"etag": etag, "state": state}, ensure_ascii=False))


def backup(world, etag, backup_dir=BACKUP_DIR):
    """the live draft, saved and read back from disk before anything replaces it. A backup that can't be saved stops the push.
    To restore: open this file in the app and push it like any other."""
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", world.get("title") or "world").strip(" ._")[:60] or "world"
    folder = Path(backup_dir) / f"{safe} ({world['shortId']})"
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
    def can_publish(self):
        return bool(self.publish.get("valid")) and not self.publish.get("errors")


def check(client, path, short_id, data_dir=DATA_DIR):
    """everything worth knowing before a push. Downloads and asks Voyage to validate; changes nothing."""
    ours = fold(read_state(path))
    live, etag = client.download(short_id)
    live_state = fold(live["initialGameState"])
    notes, blocked = [], []
    for k in VOYAGE_OWN:
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
    draft = client.validate(ours, "draft")
    publish = client.validate(ours, "publish")
    if draft.get("errors") or not draft.get("valid"):
        blocked.append("Voyage would refuse to save this file. Fix the errors below first.")
    base = read_baseline(data_dir, short_id)
    edits = []
    if base and base["etag"] != etag:
        edits = diff(authored(fold(base["state"])), authored(live_state))
    changes = diff(authored(live_state), authored(ours))
    if not changes:
        blocked.append("The live draft already holds this file. Nothing to push.")
    return Check(short_id, live.get("title") or short_id, etag, live, ours, draft, publish,
                 group(draft, publish, local_checks(ours)), changes, edits, base is None, blocked, notes)


@dataclass
class Pushed:
    etag: str
    backup: Path
    not_kept: list      # what Voyage changed or dropped of what was sent, as (kind, path, sent, stored)


class PushStopped(Exception):
    """nothing was written, or the outcome is stated in the message"""


def push(client, c, typed_title=None, data_dir=DATA_DIR, backup_dir=BACKUP_DIR):
    if c.blocked:
        raise PushStopped(" ".join(c.blocked))
    if c.moved and (typed_title or "").strip() != c.title.strip():
        raise PushStopped("This draft was edited in Studio since your last push. Type the world's exact title to replace those edits.")
    live, etag = client.download(c.short_id)
    if etag != c.etag:
        raise PushStopped("The draft changed in Studio after you pressed Check. Nothing was written. Press Check again.")
    try:
        saved = backup(live, etag, backup_dir)
    except OSError as e:
        raise PushStopped(f"The backup couldn't be saved ({e}), so nothing was pushed.") from e
    world = {**live, "initialGameState": c.sending}   # title, image, tags, description and visibility stay Studio's
    try:
        new_etag = client.replace(world, etag)
    except ApiError as e:
        if e.status == 412:
            raise PushStopped("The draft changed in Studio during the push, so nothing was overwritten. Press Check again.") from e
        if e.code == "request_status_unknown" or e.status >= 500 or e.status == 0:
            raise PushStopped(f"Voyage didn't confirm the push ({e}). It may or may not have landed. Press Check to see what the draft holds. Your backup: {saved}") from e
        raise PushStopped(f"Voyage refused the push, so nothing changed: {e}") from e
    except OSError as e:   # requests' connection and timeout errors
        raise PushStopped(f"The connection dropped during the push ({type(e).__name__}). It may or may not have landed. Press Check to see what the draft holds. Your backup: {saved}") from e
    try:
        back, back_etag = client.download(c.short_id)
    except (ApiError, OSError) as e:
        raise PushStopped(f"The push landed, but reading it back failed ({e}). Press Check to confirm. Your backup: {saved}") from e
    stored = fold(back["initialGameState"])
    write_baseline(data_dir, c.short_id, back_etag or new_etag, stored)
    return Pushed(back_etag or new_etag, saved, lost_on_save(authored(c.sending), authored(stored)))
