"""Before and after as one text with the removed words struck out and the added ones marked, so a small edit in a long NPC card can be
found. Display only."""
import difflib
import html
import json
import re

TOKEN = re.compile(r"\s+|\w+\s*|[^\w\s]\s*")   # a word or mark carries the space after it, so spaces are no tokens of their own
WORD = re.compile(r"\w")
CONTEXT = 30   # unchanged words kept either side of an edit; longer runs are cut to "…"
MAX_TOKENS = 20000   # both sides together, about 10,000 words each: under half a second at worst (timed 2026-11-09). Past it,
                     # the match freezes the window for seconds, so Before and After are shown alone


def as_text(value):
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=1)


def _esc(text):
    return html.escape(text).replace("\n", "<br>")


def marked(old, new, removed_style, added_style):
    """(HTML, words removed, words added), or None when the texts are too long to match. Punctuation isn't counted as a word. An
    unchanged run longer than twice CONTEXT keeps CONTEXT words beside each edit; one at the very start or end keeps only the side
    next to the edit."""
    a, b = TOKEN.findall(as_text(old)), TOKEN.findall(as_text(new))
    if len(a) + len(b) > MAX_TOKENS:
        return None
    out, gone, came = [], 0, 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            run = a[i1:i2]
            if len(run) > 2 * CONTEXT:
                head = run[:CONTEXT] if out else []
                tail = run[-CONTEXT:] if i2 < len(a) or j2 < len(b) else []
                out.append(_esc("".join(head)) + " <b>…</b> " + _esc("".join(tail)))
            else:
                out.append(_esc("".join(run)))
            continue
        if i2 > i1:
            gone += sum(1 for t in a[i1:i2] if WORD.match(t))
            out.append(f"<span style='{removed_style}'>{_esc(''.join(a[i1:i2]))}</span>")
        if j2 > j1:
            came += sum(1 for t in b[j1:j2] if WORD.match(t))
            out.append(f"<span style='{added_style}'>{_esc(''.join(b[j1:j2]))}</span>")
    return "".join(out), gone, came
