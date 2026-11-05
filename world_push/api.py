"""Voyage's Creator API (https://api.aidungeon.com/creator/v1): only the calls this app needs. It never publishes."""
import json
import re
import time

import requests

BASE = "https://api.aidungeon.com/creator/v1"
MAX_BODY = 64 * 1024 * 1024   # Voyage's request limit
RETRYABLE = {"studio_unavailable", "rate_limited", "request_in_progress"}
COMPAT_REFUSAL = re.compile(r"requires a newer version of Voyage \(v\d+\.(\d+)\) than this environment supports \(v\d+\.(\d+)\)")


class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(f"HTTP {status} {code}: {message}")
        self.status, self.code, self.message = status, code, message


def key_problem(key):
    """why this text cannot be a Creator API key, or None"""
    if not key.strip():
        return "Paste your API key first."
    if not key.strip().startswith("sk-voyage-v1-"):
        return "That isn't a Voyage API key. They start with sk-voyage-v1-"
    return None


def _rows(data, key):
    rows = data.get("data", data) if isinstance(data, dict) else data
    if isinstance(rows, dict):
        found = [rows[k] for k in (key, "items") if isinstance(rows.get(k), list)]
        if not found:
            raise ApiError(200, "unexpected_shape", f"no list of {key} in Voyage's answer")
        rows = found[0]
    if not isinstance(rows, list):
        raise ApiError(200, "unexpected_shape", f"no list of {key} in Voyage's answer")
    return rows


class Client:
    def __init__(self, key, session=None, base=BASE, sleep=time.sleep, tries=4):
        self.key, self.base, self.sleep, self.tries = key.strip(), base, sleep, tries
        self.http = session or requests.Session()

    def call(self, method, path, body=None, headers=None):
        """(json, response headers). Retries only what Voyage calls safe to retry. Sends no Origin header: Voyage refuses those."""
        h = {"Authorization": f"Bearer {self.key}", "Accept": "application/json", **(headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            h["Content-Type"] = "application/json"
            if len(data) > MAX_BODY:
                raise ApiError(0, "too_large", f"{len(data) / 2**20:.1f} MiB is over Voyage's 64 MiB limit; nothing was sent")
        for attempt in range(self.tries):
            r = self.http.request(method, self.base + path, data=data, headers=h, timeout=300)
            got = r.json() if r.content and "json" in r.headers.get("Content-Type", "json") else None
            if 200 <= r.status_code < 300:
                return got, r.headers
            err = got.get("error", {}) if isinstance(got, dict) else {}
            code = err.get("code", "")
            if (r.status_code == 429 or code in RETRYABLE) and attempt < self.tries - 1:
                self.sleep(float(r.headers.get("Retry-After", 5)))
                continue
            raise ApiError(r.status_code, code or "?", err.get("message", (r.text or "")[:300]))
        raise ApiError(0, "retries_exhausted", f"{method} {path}")

    def worlds(self):
        """every world and mod this key's account owns"""
        out, seen = [], set()
        for page in range(200):
            data, _ = self.call("GET", f"/worlds?page={page}")
            fresh = [r for r in _rows(data, "worlds") if r.get("shortId") not in seen]
            if not fresh:
                return out
            seen.update(r.get("shortId") for r in fresh)
            out += fresh
        raise ApiError(200, "too_many_pages", "Voyage kept returning new worlds past page 200")

    def download(self, short_id):
        """(the world envelope, its ETag). No ETag stops here: a write without If-Match could overwrite someone's edits."""
        data, headers = self.call("GET", f"/worlds/{short_id}")
        world = data.get("data", data).get("world") if isinstance(data, dict) else None
        if not isinstance(world, dict) or "initialGameState" not in world:
            raise ApiError(200, "unexpected_shape", "Voyage's answer holds no world")
        etag = (headers.get("ETag") or "").strip()
        if etag.startswith("W/"):
            etag = etag[2:]
        if not etag:
            raise ApiError(200, "no_etag", "Voyage gave no revision tag, so nothing can be written safely")
        return world, etag

    def validate(self, state, stage):
        """Voyage's own check. A refusal naming a newer compatibilityRevision is Voyage's own bump on save: `state` is lowered in
        place to the number the refusal names (that section is Voyage's, and the lowered one is what the write must send)."""
        try:
            return self._validate(state, stage)
        except ApiError as e:
            m = COMPAT_REFUSAL.search(e.message or "") if e.code == "invalid_game_state" else None
            if not m or "compatibilityRevision" not in state or int(state["compatibilityRevision"]) <= int(m.group(2)):
                raise
            state["compatibilityRevision"] = int(m.group(2))
            return self._validate(state, stage)

    def _validate(self, state, stage):
        data, _ = self.call("POST", "/validate", {"stage": stage, "world": {"initialGameState": state}})
        if not isinstance(data, dict) or "valid" not in data.get("data", {}):
            raise ApiError(200, "unexpected_shape", "Voyage's check gave no verdict")
        return data["data"]

    def replace(self, world, etag):
        if not etag:
            raise ApiError(0, "no_etag", "refusing a write without a revision tag")
        _, headers = self.call("PUT", f"/worlds/{world['shortId']}", {"world": world}, {"If-Match": etag})
        return headers.get("ETag")
