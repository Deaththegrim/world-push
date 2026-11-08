"""Whether a newer World Push is out. Asks GitHub's public releases list and nothing else; it sends no key and no world."""
import re

import requests

RELEASES = "https://api.github.com/repos/Deaththegrim/world-push/releases?per_page=10"


def _version(tag):
    found = re.findall(r"\d+", tag or "")
    return tuple(int(n) for n in found[:3]) if found else None


def newer(current, releases):
    """(tag, page) of the newest release above `current`, or None. Drafts don't count; prereleases do, since every build is one so far."""
    mine = _version(current)
    best = None
    for r in releases or []:
        v = _version(r.get("tag_name")) if isinstance(r, dict) and not r.get("draft") else None
        if v and mine and v > mine and (best is None or v > best[0]):
            best = (v, r.get("tag_name"), r.get("html_url"))
    return best[1:] if best else None


def check(current, session=None):
    r = (session or requests).get(RELEASES, headers={"Accept": "application/vnd.github+json"}, timeout=10)
    r.raise_for_status()
    return newer(current, r.json())
