"""The window. All the work lives in flow.py; this only shows it and runs it off the UI thread."""
import html
import json
import os
import sys
import traceback
from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QStandardPaths, Qt, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QPalette
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow,
                               QMessageBox, QPushButton, QSplitter, QTabWidget, QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import __version__, flow
from .api import ApiError, Client, key_problem
from .tokens import PALETTES
from .worldfile import WorldFileError

C = PALETTES["slate-violet"]
SEVERITY = {"error": ("Blocks saving", C["danger"]), "publish": ("Blocks publishing", C["warning"]), "warning": ("Warning", C["text-muted"])}
ItemRole = Qt.ItemDataRole.UserRole + 1


def explain(e):
    """an exception as words a person can act on"""
    if isinstance(e, (WorldFileError, flow.PushStopped)):
        return str(e)
    if isinstance(e, ApiError):
        if e.status == 401:
            return "Voyage didn't accept your API key. Press Change key and paste a current one."
        if e.status == 403:
            return "Your API key can't reach that world. A key only works on worlds its own account owns."
        return f"Voyage answered with an error: {e}"
    if isinstance(e, OSError):
        return f"Couldn't reach Voyage or read a file: {e}"
    return f"Something unexpected went wrong: {type(e).__name__}: {e}"


class Signals(QObject):
    done = Signal(object)
    failed = Signal(object)


class Task(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn, self.signals = fn, Signals()

    @Slot()
    def run(self):
        try:
            out = self.fn()
        except Exception as e:   # shown to the person by the failed slot
            traceback.print_exc()
            self.signals.failed.emit(e)
        else:
            self.signals.done.emit(out)


def count(rows, word):
    n = len(rows or [])
    return f"{n:,} {word}" + ("" if n == 1 else "s")


def preview(value):
    if value is None:
        return "(nothing)"
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=1)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"World Push {__version__}: an unofficial tool for Voyage worlds")
        self.setMinimumSize(900, 600)
        self.resize(1200, 800)
        self.setAcceptDrops(True)
        self.pool = QThreadPool.globalInstance()
        self.client, self.path, self.result = None, None, None
        self.tasks = set()
        self.working = False

        root = QWidget(self)
        self.setCentralWidget(root)
        box = QVBoxLayout(root)
        box.setContentsMargins(16, 16, 16, 16)
        box.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(QLabel("World"))
        self.world = QComboBox(self)
        self.world.setMinimumWidth(320)
        self.world.currentIndexChanged.connect(self.invalidate)
        row.addWidget(self.world, 1)
        self.refresh_btn = QPushButton("Refresh list", self)
        self.refresh_btn.clicked.connect(self.load_worlds)
        row.addWidget(self.refresh_btn)
        self.key_btn = QPushButton("Change key", self)
        self.key_btn.clicked.connect(self.ask_key)
        row.addWidget(self.key_btn)
        box.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("File"))
        self.file = QLineEdit(self)
        self.file.setReadOnly(True)
        self.file.setPlaceholderText("Drop a world JSON anywhere on this window, or press Browse")
        row.addWidget(self.file, 1)
        self.browse_btn = QPushButton("Browse", self)
        self.browse_btn.clicked.connect(self.browse)
        row.addWidget(self.browse_btn)
        self.check_btn = QPushButton("Check", self)
        self.check_btn.setObjectName("Primary")
        self.check_btn.setToolTip("Asks Voyage about this file. Writes nothing.")
        self.check_btn.clicked.connect(self.run_check)
        row.addWidget(self.check_btn)
        box.addLayout(row)

        self.banner = QFrame(self)
        self.banner.setObjectName("Banner")
        inner = QVBoxLayout(self.banner)
        self.banner_title = QLabel("Pick a world and a file, then press Check.", self.banner)
        self.banner_title.setObjectName("BannerTitle")
        self.banner_title.setWordWrap(True)
        self.banner_title.setTextFormat(Qt.TextFormat.PlainText)   # error text can hold a server's HTML page
        self.banner_body = QLabel("Check writes nothing to Voyage.", self.banner)
        self.banner_body.setObjectName("Muted")
        self.banner_body.setWordWrap(True)
        self.banner_body.setTextFormat(Qt.TextFormat.PlainText)
        self.banner_body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        inner.addWidget(self.banner_title)
        inner.addWidget(self.banner_body)
        box.addWidget(self.banner)

        self.tabs = QTabWidget(self)
        self.problems, self.problem_text = self._pane("Problems", ["Problem", "How many"], self.show_problem)
        self.changes, self.change_text = self._pane("What changes", ["Field", "Change"], self.show_change)
        self.edits, self.edit_text = self._pane("Edits made in Studio", ["Field", "Change"], self.show_change)
        box.addWidget(self.tabs, 1)

        row = QHBoxLayout()
        self.backups_btn = QPushButton("Open backups folder", self)
        self.backups_btn.clicked.connect(self.open_backups)
        row.addWidget(self.backups_btn)
        row.addStretch(1)
        note = QLabel("A push replaces the draft and never publishes. Publishing stays in Studio.", self)
        note.setObjectName("Muted")
        row.addWidget(note)
        self.push_btn = QPushButton("Back up and push", self)
        self.push_btn.setObjectName("Primary")
        self.push_btn.setEnabled(False)
        self.push_btn.clicked.connect(self.run_push)
        row.addWidget(self.push_btn)
        box.addLayout(row)

        self._set_edits_tab(0)

    def _pane(self, title, headers, on_select):
        split = QSplitter(self)
        tree = QTreeWidget(split)
        tree.setHeaderLabels(headers)
        tree.setColumnWidth(0, 460)
        tree.currentItemChanged.connect(on_select)
        text = QTextBrowser(split)
        text.setOpenExternalLinks(False)
        split.addWidget(tree)
        split.addWidget(text)
        split.setSizes([640, 520])
        self.tabs.addTab(split, title)
        return tree, text

    def _set_edits_tab(self, count):
        i = self.tabs.count() - 1
        self.tabs.setTabVisible(i, bool(count))
        self.tabs.setTabText(i, f"Edits made in Studio ({count:,})")

    def set_banner(self, state, title, body=""):
        self.banner.setProperty("state", state)
        self.banner.style().unpolish(self.banner)
        self.banner.style().polish(self.banner)
        self.banner_title.setText(title)
        self.banner_body.setText(body)

    def busy(self, on):
        self.working = on
        for b in (self.check_btn, self.browse_btn, self.refresh_btn, self.key_btn, self.world):
            b.setEnabled(not on)
        if on:
            self.push_btn.setEnabled(False)

    def start(self, fn, done, failed=None):
        task = Task(fn)
        task.setAutoDelete(False)
        self.tasks.add(task)   # the signal object must outlive the run

        def finish(slot):
            def go(value):
                self.tasks.discard(task)
                try:
                    slot(value)
                except Exception as e:   # a failure in the follow-up must not leave the window disabled and silent
                    traceback.print_exc()
                    self.on_failed(e)
            return go

        task.signals.done.connect(finish(done))
        task.signals.failed.connect(finish(failed or self.on_failed))
        self.pool.start(task)

    def on_failed(self, e):
        self.busy(False)
        self.set_banner("stop", "That didn't work.", explain(e))

    # the key and the world list

    def startup(self):
        key = flow.load_key()
        if key:
            self.client = Client(key)
            self.load_worlds()
        else:
            self.ask_key()

    def ask_key(self):
        text = ("Paste your Voyage API key. In Studio: open any world, then Settings, then API keys.\n\n"
                "It stays on this computer and is only sent to Voyage.")
        key, ok = QInputDialog.getText(self, "Your API key", text, QLineEdit.EchoMode.Password)
        if not ok:
            return
        bad = key_problem(key)
        if bad:
            self.set_banner("stop", bad, "Press Change key to try again.")
            return
        client = Client(key)
        self.busy(True)
        self.set_banner("", "Checking your key...")

        def accepted(worlds):
            flow.save_key(key)
            self.client = client
            self.on_worlds(worlds)

        self.start(client.worlds, accepted)

    def load_worlds(self):
        if not self.client:
            self.ask_key()
            return
        self.busy(True)
        self.set_banner("", "Loading your worlds...")
        self.start(self.client.worlds, self.on_worlds)

    def on_worlds(self, worlds):
        self.busy(False)
        keep = self.world.currentData()
        self.world.blockSignals(True)
        self.world.clear()
        for w in sorted(worlds, key=lambda r: (r.get("title") or "").lower()):
            kind = " (mod)" if w.get("isMod") else ""
            self.world.addItem(f"{w.get('title') or 'Untitled'}{kind}  [{w.get('shortId')}]", w.get("shortId"))
        at = self.world.findData(keep)
        if at >= 0:
            self.world.setCurrentIndex(at)
        self.world.blockSignals(False)
        self.invalidate()
        self.set_banner("", f"{len(worlds)} worlds on this key. Pick a world and a file, then press Check.", "Check writes nothing to Voyage.")

    # the file

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Pick a world JSON", str(Path(self.path).parent) if self.path else "", "World JSON (*.json);;All files (*)")
        if path:
            self.set_file(path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def closeEvent(self, event):
        if self.working:   # a push can't be taken back, and closing would lose its outcome
            event.ignore()
            self.set_banner("warn", "Still working. Wait for this to finish before closing.", self.banner_body.text())
        else:
            event.accept()

    def dropEvent(self, event):
        if self.working:   # the running check belongs to the file it started with
            return
        urls = event.mimeData().urls()
        if urls:
            self.set_file(urls[0].toLocalFile())

    def set_file(self, path):
        self.path = path
        self.file.setText(path)
        self.invalidate()

    def invalidate(self, *_):
        """a check belongs to one file and one world"""
        self.result = None
        self.push_btn.setEnabled(False)

    # check

    def run_check(self):
        short_id = self.world.currentData()
        if not self.client or not short_id or not self.path:
            self.set_banner("warn", "Pick a world and a file first.")
            return
        client, path = self.client, self.path
        self.busy(True)
        self.set_banner("", "Checking...", "Downloading the live draft and asking Voyage. A big world can take a minute.")
        self.start(lambda: flow.check(client, path, short_id), self.on_checked)

    def on_checked(self, c):
        self.busy(False)
        self.result = c
        self.fill_problems(c)
        self.fill_changes(self.changes, c.changes, self.change_text, "from the live draft to your file")
        self.fill_changes(self.edits, c.studio_edits, self.edit_text, "from your last push to the live draft")
        self._set_edits_tab(len(c.studio_edits))
        self.tabs.setTabText(0, f"Problems ({sum(len(f.items) for f in c.findings):,})")
        self.tabs.setTabText(1, f"What changes ({len(c.changes):,})")
        draft, publish = c.draft, c.publish
        lines = [f"Save as a draft: {'yes' if not c.blocked and draft.get('valid') else 'no'}. Publish: {'yes' if c.can_publish else 'no'}. "
                 f"Voyage's check: {count(draft.get('errors'), 'error')} at draft, {count(publish.get('errors'), 'error')} at publish, "
                 f"{count(publish.get('warnings'), 'warning')}."] + c.notes
        if c.blocked:
            self.set_banner("stop", "This can't be pushed yet.", "\n".join(c.blocked + lines))
        elif c.moved:
            self.set_banner("warn", f"{c.title} was edited in Studio since your last push.",
                            "\n".join([f"Pushing replaces {len(c.studio_edits):,} Studio edits; see the Edits made in Studio tab. You'll have to type the world's title to confirm."] + lines))
        elif c.first_push and c.can_publish:
            self.set_banner("warn", "Ready, but this computer hasn't pushed this world before.",
                            "\n".join(["So it can't tell Studio edits from your own. Read What changes first: anything you don't recognise would be replaced. You'll type the world's title to confirm."] + lines))
        elif not c.can_publish:
            self.set_banner("warn", "This can be saved as a draft, but you can't publish it yet.", "\n".join(lines))
        else:
            self.set_banner("ok", "Ready to push.", "\n".join(lines))
        self.push_btn.setEnabled(not c.blocked)

    def fill_problems(self, c):
        self.problems.clear()
        self.problem_text.clear()
        first = None
        for f in c.findings:
            label, colour = SEVERITY[f.severity]
            top = QTreeWidgetItem(self.problems, [f"{label}: {f.title}", f"{len(f.items):,}"])
            top.setForeground(0, QBrush(QColor(colour)))
            top.setData(0, ItemRole, (f, None))
            first = first or top
            for where, message in f.items:
                child = QTreeWidgetItem(top, [where.replace('$.', ''), ""])
                child.setData(0, ItemRole, (f, (where, message)))
        if first:
            self.problems.setCurrentItem(first)
        else:
            self.problem_text.setPlainText("Voyage found nothing to report.")

    def show_problem(self, item, *_):
        if not item:
            return
        f, one = item.data(0, ItemRole)
        if one is None and len(f.items) == 1:
            one = f.items[0]
        parts = [f"<h3>{html.escape(f.title)}</h3><p><b>What's wrong</b><br>{html.escape(f.wrong)}</p><p><b>How to fix it</b><br>{html.escape(f.fix)}</p>"]
        if one:
            parts.append(f"<p><b>Where</b><br>{html.escape(one[0])}</p><p><b>Voyage says</b><br>{html.escape(one[1])}</p>")
        else:
            parts.append(f"<p>{len(f.items):,} places. Expand this line to see each one, or look at one below.</p>"
                         f"<p><b>For example</b><br>{html.escape(f.items[0][0])}<br>{html.escape(f.items[0][1])}</p>")
        self.problem_text.setHtml("".join(parts))

    def fill_changes(self, tree, changes, text, intro):
        tree.clear()
        text.setPlainText(f"{len(changes):,} changes {intro}." if changes else "No changes.")
        sections = {}
        for kind, path, old, new in changes:
            section = str(path[0]) if path else "(whole world)"
            top = sections.get(section)
            if top is None:
                top = sections[section] = QTreeWidgetItem(tree, [section, ""])
            child = QTreeWidgetItem(top, [" > ".join(map(str, path[1:])) or section, kind])
            child.setData(0, ItemRole, (kind, path, old, new))
        for top in sections.values():
            top.setText(1, f"{top.childCount():,}")

    def show_change(self, item, *_):
        if not item or not item.data(0, ItemRole):
            return
        kind, path, old, new = item.data(0, ItemRole)
        pane = self.change_text if item.treeWidget() is self.changes else self.edit_text
        pane.setHtml(f"<h3>{html.escape(' > '.join(map(str, path)))}</h3><p>{kind}</p><p><b>Before</b></p><pre style='white-space:pre-wrap'>{html.escape(preview(old))}</pre>"
                     f"<p><b>After</b></p><pre style='white-space:pre-wrap'>{html.escape(preview(new))}</pre>")

    # push

    def run_push(self):
        c = self.result
        if not c or c.blocked:
            return
        typed = None
        where = f"{c.title} [{c.short_id}]"
        name = Path(self.path).name
        if c.needs_title:
            why = (f"{where} was edited in Studio since your last push from this app. Pushing replaces {len(c.studio_edits):,} of those edits."
                   if c.moved else f"This computer hasn't pushed {where} before, so it can't tell if Studio holds edits you'd want to keep. Check the What changes tab.")
            typed, ok = QInputDialog.getText(self, "Replace this draft?",
                                             f"{why}\n\nFile: {name}\n{len(c.changes):,} changes. A backup of the live draft is saved first. Nothing gets published.\n\n"
                                             f"Type the world's title to confirm:\n{c.title}")
            if not ok:
                return
            if typed.strip() != c.title.strip():
                self.set_banner("warn", "The title didn't match, so nothing was pushed.")
                return
        else:
            answer = QMessageBox.question(self, "Push to draft?", f"Replace the draft of {where} with {name}?\n\n{len(c.changes):,} changes. "
                                          "A backup of the live draft is saved first. Nothing gets published.")
            if answer != QMessageBox.StandardButton.Yes:
                return
        client = self.client
        self.busy(True)
        self.set_banner("", "Backing up and pushing...", "Don't close the app until this finishes.")
        self.start(lambda: flow.push(client, c, typed), self.on_pushed)

    def on_pushed(self, p):
        self.busy(False)
        self.invalidate()
        where = f"Backup of the draft as it was: {p.backup}"
        if p.raced:
            self.set_banner("warn", "Pushed, but someone saved in Studio straight after.", f"Your push landed, then the draft changed again. Press Check to see those edits.\n{where}")
        elif p.not_kept:
            paths = "\n".join(f"  {' > '.join(map(str, d[1]))}" for d in p.not_kept[:12])
            more = f"\n  ...and {len(p.not_kept) - 12:,} more" if len(p.not_kept) > 12 else ""
            self.set_banner("warn", f"Pushed, but Voyage changed or dropped {len(p.not_kept):,} things you sent.", f"{where}\n{paths}{more}")
        else:
            self.set_banner("ok", "Pushed, and it read back the same. Not published.", where)

    def open_backups(self):
        try:
            flow.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.set_banner("warn", "Couldn't open the backups folder.", str(e))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(flow.BACKUP_DIR)))


def install_theme(app):
    app.setStyle("Fusion")
    pal = QPalette()
    role = QPalette.ColorRole
    for r, token in ((role.Window, "bg"), (role.WindowText, "text"), (role.Base, "surface"), (role.AlternateBase, "surface-elev"), (role.ToolTipBase, "surface-overlay"),
                     (role.ToolTipText, "text"), (role.Text, "text"), (role.Button, "surface-elev"), (role.ButtonText, "text"), (role.BrightText, "danger"), (role.Link, "accent-soft"),
                     (role.Highlight, "accent"), (role.HighlightedText, "text-on-accent"), (role.PlaceholderText, "text-faint")):
        pal.setColor(r, QColor(C[token]))
    for r in (role.WindowText, role.Text, role.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, r, QColor(C["text-faint"]))
    app.setPalette(pal)
    qss = files("world_push.assets").joinpath("theme.qss").read_text(encoding="utf-8")
    for k, v in C.items():
        qss = qss.replace("{" + k + "}", v)
    app.setStyleSheet(qss)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("World Push")
    install_theme(app)
    documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)   # the real one, under OneDrive too
    if documents:
        flow.BACKUP_DIR = Path(documents) / "World Push backups"
    win = MainWindow()
    win.show()
    if os.environ.get("WORLD_PUSH_SMOKE"):   # the build check: the window and its theme load inside the packaged app
        return 0
    win.startup()
    if len(sys.argv) > 1:
        win.set_file(sys.argv[1])
    return app.exec()
