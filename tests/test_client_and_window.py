import copy
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QCloseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from world_push import app as A  # noqa: E402
from world_push.api import ApiError, Client  # noqa: E402


class R:
    def __init__(self, status, body, headers=None):
        self.status_code, self.text = status, body if isinstance(body, str) else json.dumps(body)
        self.content, self.headers = self.text.encode(), {"Content-Type": "application/json", **(headers or {})}

    def json(self):
        return json.loads(self.text)


class Session:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def request(self, method, url, data=None, headers=None, timeout=None):
        self.calls.append((method, url, json.loads(data) if data else None, headers))
        return self.answers.pop(0)


def client(*answers, waits=None):
    return Client("sk-voyage-v1-x", session=Session(*answers), sleep=(waits if waits is not None else []).append)


@pytest.mark.parametrize("answer", [R(502, {"error": "bad gateway"}), R(502, "<html>not json</html>")])
def test_a_gateways_odd_error_is_still_an_api_error(answer):
    with pytest.raises(ApiError) as e:
        client(answer).call("GET", "/x")
    assert e.value.status == 502


def test_retry_after_as_a_date_waits_the_default_and_a_long_one_is_told_not_slept():
    waits = []
    c = client(R(429, {}, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}), R(200, {}), waits=waits)
    c.call("GET", "/x")
    assert waits == [5.0]
    waits = []
    with pytest.raises(ApiError, match="Try again later"):
        client(R(429, {}, {"Retry-After": "3600"}), waits=waits).call("GET", "/x")
    assert not waits


def test_a_refused_revision_is_lowered_in_what_gets_sent():
    refusal = R(400, {"error": {"code": "invalid_game_state", "message": "requires a newer version of Voyage (v37.13) than this environment supports (v37.10)"}})
    c = client(refusal, R(200, {"data": {"valid": True, "errors": [], "warnings": []}}))
    state = {"compatibilityRevision": 13}
    c.validate(state, "draft")
    assert state["compatibilityRevision"] == 10 and c.http.calls[1][2]["world"]["initialGameState"]["compatibilityRevision"] == 10


def test_no_origin_header_and_a_weak_etag_is_unwrapped():
    c = client(R(200, {"data": {"world": {"initialGameState": {}}}}, {"ETag": 'W/"abc"'}))
    assert c.download("x")[1] == '"abc"'
    assert "Origin" not in c.http.calls[0][3]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp):
    w = A.MainWindow()
    yield w
    w.working = False
    w.close()


def test_a_drop_during_a_check_is_ignored(win, tmp_path):
    from PySide6.QtCore import QMimeData, QPointF, QUrl
    from PySide6.QtGui import QDropEvent
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tmp_path / "b.json"))])
    event = QDropEvent(QPointF(1, 1), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    win.set_file("a.json")
    win.busy(True)
    win.dropEvent(event)
    assert win.path == "a.json"
    win.busy(False)
    win.dropEvent(event)
    assert win.path.endswith("b.json")


def test_the_window_refuses_to_close_while_working(win):
    win.busy(True)
    event = QCloseEvent()
    win.closeEvent(event)
    assert not event.isAccepted()
    win.busy(False)
    event = QCloseEvent()
    win.closeEvent(event)
    assert event.isAccepted()


def test_error_text_can_not_render_as_html(win):
    win.on_failed(ApiError(502, "?", "<html><head><title>Error</title><style>x"))
    assert win.banner_body.textFormat() == Qt.TextFormat.PlainText and win.banner_title.textFormat() == Qt.TextFormat.PlainText
    assert "<html>" in win.banner_body.text()


def test_a_failing_follow_up_does_not_leave_the_window_stuck(win, qapp):
    def boom(_):
        raise PermissionError("no")
    win.busy(True)
    win.start(lambda: 1, boom)
    win.pool.waitForDone(3000)
    qapp.processEvents()
    qapp.processEvents()
    assert not win.working and win.check_btn.isEnabled() and "no" in win.banner_body.text()


def test_a_problem_reads_in_plain_words_and_help_stays_beside_a_hidden_edits_tab(qapp):
    from types import SimpleNamespace
    from world_push.findings import group
    w = A.MainWindow()
    path = "$.npcs.Ann"
    code = "game-state.limit.npc"
    w.fill_problems(SimpleNamespace(findings=group({"errors": [{"code": code, "path": path, "message": 'NPC "Ann" exceeds the 12,000 character limit by 57 characters'}]},
                                                   {"errors": [{"code": code, "path": path, "message": 'NPC "Ann" exceeds the 8,000 character limit by 4,057 characters'}]})))
    shown = w.problem_text.toPlainText()
    assert "Voyage won't save" in shown and "Cut 57 characters to save" in shown and "Cut 4,057 characters to publish" in shown and "NPC: Ann" in shown and "$.npcs" not in shown
    assert w.problems.topLevelItem(0).child(0).text(0) == "NPC: Ann"
    assert w.tabs.tabText(w.edits_tab).startswith("Edits made in Studio")
    w._set_edits_tab(3)
    assert w.tabs.tabText(w.edits_tab) == "Edits made in Studio (3)" and w.tabs.isTabVisible(w.edits_tab)
    w._set_edits_tab(0)
    assert not w.tabs.isTabVisible(w.edits_tab) and w.tabs.isTabVisible(w.tabs.indexOf(w.help_text))
    assert "12,000" in w.help_text.toPlainText()


def test_settings_survive_a_restart_and_a_broken_file_is_a_fresh_start(tmp_path):
    from world_push import flow
    flow.save_settings(tmp_path, world="abc", file="/x/w.json")
    flow.save_settings(tmp_path, world="def")
    assert flow.load_settings(tmp_path) == {"world": "def", "file": "/x/w.json"}
    (tmp_path / "settings.json").write_text("{nope", encoding="utf-8")
    assert flow.load_settings(tmp_path) == {}


def test_only_a_newer_release_is_offered():
    from world_push.updates import newer
    rel = [{"tag_name": "v0.1.2", "html_url": "a"}, {"tag_name": "v0.1.10", "html_url": "b"}, {"tag_name": "v0.2.0", "html_url": "c", "draft": True},
           {"tag_name": "junk"}, "junk"]
    assert newer("0.1.2", rel) == ("v0.1.10", "b")
    assert newer("0.1.10", rel) is None and newer("0.1.2", []) is None


def test_a_saved_file_is_checked_again_only_once_it_was_checked(win, qapp, tmp_path, monkeypatch):
    f = tmp_path / "w.json"
    f.write_text("{}", encoding="utf-8")
    runs = []
    monkeypatch.setattr(win, "run_check", lambda: runs.append(1))
    win.set_file(str(f))
    assert str(f) in win.watcher.files()
    win.file_saved(str(f))
    assert not win.recheck.isActive()            # never checked this session: a save does nothing
    win.checked_path = str(f)
    win.file_saved(str(f))
    assert win.recheck.isActive() and not win.push_btn.isEnabled()
    win.recheck.stop()
    win.working = True
    win.recheck_now()
    assert not runs and win.recheck.isActive()   # waits for the running job
    win.recheck.stop()
    win.working = False
    win.recheck_now()
    assert runs == [1]


def test_a_check_that_changes_under_the_confirm_question_stops_the_push(win, monkeypatch):
    from types import SimpleNamespace
    c = SimpleNamespace(blocked=[], needs_title=False, title="T", short_id="s", changes=[])
    win.result, win.path = c, "/x/w.json"
    def answer(*_a, **_k):
        win.result = None   # a recheck landed while the question was open
        return A.QMessageBox.StandardButton.Yes
    monkeypatch.setattr(A.QMessageBox, "question", answer)
    started = []
    monkeypatch.setattr(win, "start", lambda *a: started.append(a))
    win.run_push()
    assert not started and "nothing was pushed" in win.banner_title.text()


def test_the_problem_filter_hides_and_counts(win):
    from types import SimpleNamespace
    from world_push.findings import Finding
    win.result = object()
    win.fill_problems(SimpleNamespace(findings=[Finding("error", "Big", "w", "f", [("$.npcs.Ann", "too long"), ("$.npcs.Bo", "too long")]),
                                                Finding("warning", "Odd", "w", "f", [("$.npcs.Cy", "odd field")])]))
    assert win.problems.topLevelItemCount() == 2 and win.copy_btn.isEnabled()
    win.severity.setCurrentIndex(win.severity.findData("warning"))
    assert win.problems.topLevelItemCount() == 1 and win.problems.topLevelItem(0).text(0) == "Warning: Odd"
    win.severity.setCurrentIndex(0)
    win.search.setText("bo")
    assert win.problems.topLevelItemCount() == 1 and win.problems.topLevelItem(0).text(1) == "1 of 2"
    win.search.setText("nothing like it")
    assert win.problems.topLevelItemCount() == 0 and "None of the 3 problems" in win.problem_text.toPlainText()
