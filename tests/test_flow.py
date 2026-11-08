import copy
import json

import pytest

from world_push import flow
from world_push.api import ApiError
from world_push.findings import group, local_checks
from world_push.worldfile import WorldFileError, diff, fold, lost_on_save, read_state

STATE = {"heroesVersion": 37, "npcs": {"Ann": {"name": "Ann", "level": 1}}, "worldVoices": {}, "compatibilityRevision": 13}


def ok(stage="draft", errors=(), warnings=()):
    return {"stage": stage, "valid": not errors, "errors": list(errors), "warnings": list(warnings)}


class Fake:
    """Voyage, as far as the flow can see it"""

    def __init__(self, state=None, stored=None):
        self.world = {"shortId": "abc", "title": "My World", "description": "keep me", "initialGameState": copy.deepcopy(state or STATE)}
        self.etag, self.puts, self.draft, self.publish, self.stored = '"1"', [], ok(), ok("publish"), stored
        self.fail_put = None

    def download(self, _):
        return copy.deepcopy(self.world), self.etag

    def validate(self, _state, stage):
        return self.draft if stage == "draft" else self.publish

    def replace(self, world, etag):
        if self.fail_put:
            raise self.fail_put
        assert etag == self.etag
        self.puts.append(world)
        self.world = copy.deepcopy(world)
        if self.stored is not None:
            self.world["initialGameState"] = copy.deepcopy(self.stored)
        self.etag = f'"{len(self.puts) + 1}"'
        return self.etag


@pytest.fixture
def dirs(tmp_path):
    return {"data_dir": tmp_path / "data", "backup_dir": tmp_path / "backups"}


def write(tmp_path, state=None, name="w.json", **change):
    s = copy.deepcopy(state or STATE)
    s["npcs"]["Ann"].update(change)
    f = tmp_path / name
    f.write_text(json.dumps(s), encoding="utf-8")
    return f


def do_check(client, path, dirs):
    return flow.check(client, path, "abc", data_dir=dirs["data_dir"])


def test_push_backs_up_the_live_draft_first_and_keeps_the_studio_page(tmp_path, dirs):
    client = Fake()
    c = do_check(client, write(tmp_path, level=2), dirs)
    assert not c.blocked and c.first_push and [d[1] for d in c.changes] == [["npcs", "Ann", "level"]]
    p = flow.push(client, c, "My World", **dirs)
    assert json.loads(p.backup.read_text(encoding="utf-8"))["world"]["initialGameState"]["npcs"]["Ann"]["level"] == 1
    assert client.puts[0]["description"] == "keep me" and client.puts[0]["initialGameState"]["npcs"]["Ann"]["level"] == 2
    assert p.not_kept == []


def test_a_backup_restores_by_pushing_it_like_any_file(tmp_path, dirs):
    client = Fake()
    p = flow.push(client, do_check(client, write(tmp_path, level=2), dirs), "My World", **dirs)
    c = do_check(client, p.backup, dirs)
    assert [(d[2], d[3]) for d in c.changes] == [(2, 1)]
    flow.push(client, c, **dirs)
    assert client.world["initialGameState"]["npcs"]["Ann"]["level"] == 1


def test_a_failed_backup_means_no_write(tmp_path, dirs):
    client = Fake()
    c = do_check(client, write(tmp_path, level=2), dirs)
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(flow.PushStopped, match="backup"):
        flow.push(client, c, "My World", data_dir=dirs["data_dir"], backup_dir=blocker)
    assert not client.puts


def test_studio_edits_since_the_last_push_need_the_typed_title(tmp_path, dirs):
    client = Fake()
    flow.push(client, do_check(client, write(tmp_path, level=2), dirs), "My World", **dirs)
    client.world["initialGameState"]["npcs"]["Ann"]["level"] = 9
    client.etag = '"studio"'
    c = do_check(client, write(tmp_path, level=3), dirs)
    assert c.moved and [d[3] for d in c.studio_edits] == [9] and not c.first_push
    for wrong in (None, "", "my world"):
        with pytest.raises(flow.PushStopped, match="title"):
            flow.push(client, c, wrong, **dirs)
    assert len(client.puts) == 1
    flow.push(client, c, "My World", **dirs)
    assert client.world["initialGameState"]["npcs"]["Ann"]["level"] == 3


def test_voyages_own_bump_is_not_read_as_a_studio_edit(tmp_path, dirs):
    client = Fake()
    flow.push(client, do_check(client, write(tmp_path, level=2), dirs), "My World", **dirs)
    client.world["initialGameState"]["compatibilityRevision"] = 14
    client.etag = '"played"'
    assert not do_check(client, write(tmp_path, level=3), dirs).moved


def test_a_draft_that_moves_after_check_stops_the_push(tmp_path, dirs):
    client = Fake()
    c = do_check(client, write(tmp_path, level=2), dirs)
    client.etag = '"later"'
    with pytest.raises(flow.PushStopped, match="after you pressed Check"):
        flow.push(client, c, "My World", **dirs)
    assert not client.puts


def test_draft_errors_block_and_publish_errors_only_warn(tmp_path, dirs):
    client = Fake()
    bad = {"code": "game-state.limit.npc", "message": 'NPC "Ann" exceeds the 8,000 character limit by 9 characters', "path": "$.npcs.Ann"}
    client.publish = ok("publish", [bad])
    c = do_check(client, write(tmp_path, level=2), dirs)
    assert not c.blocked and not c.can_publish and c.findings[0].severity == "publish"
    client.draft = ok("draft", [bad])
    c = do_check(client, write(tmp_path, level=2), dirs)
    assert c.blocked and c.findings[0].severity == "error" and len(c.findings[0].items) == 1
    with pytest.raises(flow.PushStopped):
        flow.push(client, c, **dirs)
    assert not client.puts


def test_a_record_over_both_limits_shows_the_publish_limit_too(tmp_path, dirs):
    """Voyage's own wording, 2026-11-06: the draft answer names 12,000, the publish answer 8,000, for the same record"""
    path = "$.npcs.Ann"
    client = Fake()
    client.draft = ok("draft", [{"code": "game-state.limit.npc", "message": 'NPC "Ann" exceeds the 12,000 character limit by 57 characters', "path": path}])
    client.publish = ok("publish", [{"code": "game-state.limit.npc", "message": 'NPC "Ann" exceeds the 8,000 character limit by 4,057 characters', "path": path}])
    f = do_check(client, write(tmp_path, level=2), dirs).findings[0]
    assert f.severity == "error" and len(f.items) == 1
    assert f.items[0][0] == path and "12,000" in f.items[0][1] and "8,000" in f.items[0][1]
    assert "publish" in f.fix


def limit(name, cap, over):
    return {"code": "game-state.limit.npc", "message": f'NPC "{name}" exceeds the {cap:,} character limit by {over:,} characters', "path": f"$.npcs.{name}"}


def test_each_record_gets_its_own_publish_limit():
    f = group({"errors": [limit("Ann", 12000, 1), limit("Bob", 12000, 2)]}, {"errors": [limit("Ann", 8000, 4001), limit("Bob", 8000, 4002)]})[0]
    said = dict(f.items)
    assert "4,001" in said["$.npcs.Ann"] and "4,002" not in said["$.npcs.Ann"]
    assert "4,002" in said["$.npcs.Bob"] and "4,001" not in said["$.npcs.Bob"]


def test_the_same_message_at_both_stages_is_not_repeated():
    bad = limit("Ann", 8000, 9)
    assert group({"errors": [bad]}, {"errors": [bad]})[0].items == [(bad["path"], bad["message"])]


def test_two_errors_on_one_place_keep_their_own_messages():
    a, b = limit("Ann", 12000, 1), limit("Ann", 12000, 2)
    assert [m for _, m in group({"errors": [a, b]}, {"errors": [a, b]})[0].items] == [a["message"], b["message"]]


def test_only_a_size_limit_is_compared_across_stages_or_told_about_drafts():
    at = {"code": "schema.bad", "path": "$.npcs.Ann"}
    f = group({"errors": [{**at, "message": "one wording"}]}, {"errors": [{**at, "message": "other wording"}]})[0]
    assert f.items[0][1] == "one wording" and "draft" not in f.fix


def test_the_size_note_fits_the_stage_and_a_warning_gets_none():
    from world_push.findings import DRAFT_CAP_NOTE, PREVIEW_CAP_NOTE
    bad = limit("Ann", 8000, 9)
    refused = group({"errors": [bad]}, {})[0].fix
    assert DRAFT_CAP_NOTE in refused and PREVIEW_CAP_NOTE not in refused
    publish_only = group({}, {"errors": [bad]})[0].fix
    assert PREVIEW_CAP_NOTE in publish_only and DRAFT_CAP_NOTE not in publish_only
    warned = group({"warnings": [bad]}, {})[0].fix
    assert DRAFT_CAP_NOTE not in warned and PREVIEW_CAP_NOTE not in warned


def test_a_publish_error_is_never_hidden_by_a_draft_error_on_the_same_place():
    at = {"code": "schema.bad", "path": "$.npcs.Ann"}
    found = group({"errors": [{**at, "message": "A"}]}, {"errors": [{**at, "message": "B"}, {**at, "message": "A"}]})
    said = [(f.severity, m) for f in found for _, m in f.items]
    assert said == [("error", "A"), ("publish", "B")]
    found = group({"errors": [{"message": "alpha"}]}, {"errors": [{"message": "beta"}]})
    assert [(f.severity, m) for f in found for _, m in f.items] == [("error", "alpha"), ("publish", "beta")]


def test_two_size_errors_on_one_place_still_show_every_publish_number():
    found = group({"errors": [limit("Ann", 12000, 1), limit("Ann", 12000, 2)]}, {"errors": [limit("Ann", 8000, 3), limit("Ann", 8000, 4)]})
    said = " ".join(m for f in found for _, m in f.items)
    assert all(n in said for n in ("by 1 ", "by 2 ", "by 3 ", "by 4 "))


def test_a_null_field_can_not_stop_a_check():
    found = group({"errors": [{"code": None, "message": None, "path": None}]}, {"errors": [{"code": "game-state.limit.npc", "message": "over", "path": None}]})
    assert all(isinstance(x, str) for f in found for item in f.items for x in item)


def test_nothing_to_push_and_another_version_are_blocked(tmp_path, dirs):
    client = Fake()
    assert any("already holds" in b for b in do_check(client, write(tmp_path), dirs).blocked)
    other = {**copy.deepcopy(STATE), "heroesVersion": 36}
    assert any("version 36" in b for b in do_check(client, write(tmp_path, other, level=2), dirs).blocked)


def test_a_conflict_writes_nothing_and_says_so_and_an_unknown_outcome_says_that(tmp_path, dirs):
    client = Fake()
    c = do_check(client, write(tmp_path, level=2), dirs)
    client.fail_put = ApiError(412, "revision_conflict", "stale")
    with pytest.raises(flow.PushStopped, match="nothing was overwritten"):
        flow.push(client, c, "My World", **dirs)
    client.fail_put = ApiError(500, "boom", "boom")
    with pytest.raises(flow.PushStopped, match="may or may not"):
        flow.push(client, c, "My World", **dirs)
    client.fail_put = ConnectionError("gone")
    with pytest.raises(flow.PushStopped, match="may or may not"):
        flow.push(client, c, "My World", **dirs)
    assert not client.puts


def test_what_voyage_drops_on_save_is_reported(tmp_path, dirs):
    state = {**copy.deepcopy(STATE), "aiInstructions": {"generateDialogue": {"custom": "", "Extra": "gone on save"}}}
    stored = {**copy.deepcopy(state), "aiInstructions": {"generateDialogue": {"custom": ""}}, "itemSettings": {"added": True}}
    client = Fake(stored=stored)
    c = do_check(client, write(tmp_path, state, level=1), dirs)
    assert any(f.title.startswith("Instructions Voyage will throw away") for f in c.findings)
    p = flow.push(client, c, "My World", **dirs)
    assert [d[1] for d in p.not_kept] == [["aiInstructions", "generateDialogue", "Extra"]]


def test_studios_mods_and_own_sections_survive_a_file_without_them(tmp_path, dirs):
    live = {**copy.deepcopy(STATE), "mods": [{"shortId": "m"}], "characterCreationMusic": "x"}
    file_state = {k: v for k, v in copy.deepcopy(STATE).items() if k != "compatibilityRevision"}
    file_state["mods"] = []
    client = Fake(live)
    c = do_check(client, write(tmp_path, file_state, level=2), dirs)
    assert c.sending["mods"] == [{"shortId": "m"}] and c.sending["compatibilityRevision"] == 13 and c.sending["characterCreationMusic"] == "x"


def test_both_layouts_compare_as_one():
    new = {"heroesVersion": 37, "triggerDefinitions": {"t": {}}, "parties": {"": {"quests": {"q": {}}}},
           "npcs": {"A": {"initialKnown": True, "relationship": 5}}}
    old = {"heroesVersion": 37, "triggers": {"t": {}}, "quests": {"q": {}}, "npcs": {"A": {"known": True, "initialRelationship": 5}}}
    assert fold(new) == fold(old)


def test_generated_quest_triggers_never_count():
    a = fold({"heroesVersion": 37, "questTriggers": {"__generated_quest_progress__/q": {}, "mine": {}}})
    assert a["questTriggers"] == {"mine": {}}


@pytest.mark.parametrize("text, words", [("{oops", "line 1"), ('{"npcs": {}}', "whole Voyage world"), ("[1]", "whole Voyage world")])
def test_a_bad_file_says_what_is_wrong(tmp_path, text, words):
    f = tmp_path / "bad.json"
    f.write_text(text)
    with pytest.raises(WorldFileError, match=words):
        read_state(f)


def test_envelopes_and_a_bom_unwrap(tmp_path):
    f = tmp_path / "e.json"
    f.write_bytes(b"\xef\xbb\xbf" + json.dumps({"data": {"world": {"initialGameState": STATE}}}).encode())
    assert read_state(f) == STATE


def test_warnings_group_by_type_with_advice_and_nothing_is_hidden():
    warnings = [{"code": "game-state.schema.unknown-field", "message": f"Unknown field 'rewardXp' is not defined {i}", "path": f"$.q{i}"} for i in range(3)]
    warnings.append({"code": "game-state.invariant.invalid-reference", "message": 'Invalid type "X" at npcs > A > type. Allowed IDs: Y', "path": "$.npcs.A.type"})
    warnings.append({"code": "brand.new", "message": "never seen", "path": "$.z"})
    found = group(ok(warnings=warnings), ok("publish", warnings=warnings))
    titles = {f.title: f for f in found}
    assert len(titles["Quest reward fields Voyage ignores"].items) == 3
    assert "npcTypes" in titles["NPC type that doesn't exist"].fix
    assert titles["brand.new"].items == [("$.z", "never seen")] and sum(len(f.items) for f in found) == 5


def test_a_voice_with_no_record_is_flagged_and_a_real_one_is_not():
    s = {"npcs": {"A": {"worldVoiceId": "Nope"}, "B": {"worldVoiceId": "Real"}}, "worldVoices": {"Real": {}}}
    found = local_checks(s)
    assert [i[0] for i in found[0].items] == ["npcs > A > worldVoiceId"]


def test_lost_on_save_ignores_what_voyage_adds_and_empties():
    assert lost_on_save({"a": 1, "e": {}}, {"a": 1.0, "b": 2}) == []
    assert diff({"a": 1}, {"a": 2}) == [("changed", ["a"], 1, 2)]


def test_a_computer_with_no_record_of_the_world_needs_the_title(tmp_path, dirs):
    """pushing from a second computer, or after a reinstall: it can't know what Studio holds"""
    client = Fake()
    c = do_check(client, write(tmp_path, level=2), dirs)
    assert c.needs_title
    with pytest.raises(flow.PushStopped, match="title"):
        flow.push(client, c, None, **dirs)
    assert not client.puts


def test_a_studio_edit_to_the_creation_music_is_seen_and_is_a_change(tmp_path, dirs):
    state = {**copy.deepcopy(STATE), "characterCreationMusic": "fantasy"}
    client = Fake(state)
    flow.push(client, do_check(client, write(tmp_path, state, level=2), dirs), "My World", **dirs)
    client.world["initialGameState"]["characterCreationMusic"] = "nonfantasy"
    client.etag = '"studio"'
    c = do_check(client, write(tmp_path, state, level=2), dirs)
    assert c.moved and [d[1] for d in c.changes] == [["characterCreationMusic"]]


def test_a_file_with_nothing_new_records_the_draft_so_later_edits_show(tmp_path, dirs):
    client = Fake()
    assert do_check(client, write(tmp_path), dirs).blocked
    client.world["initialGameState"]["npcs"]["Ann"]["level"] = 9
    client.etag = '"studio"'
    c = do_check(client, write(tmp_path, level=2), dirs)
    assert c.moved and not c.first_push


def test_trouble_after_a_landed_push_says_it_landed(tmp_path, dirs, monkeypatch):
    client = Fake()
    c = do_check(client, write(tmp_path, level=2), dirs)

    def broken(*_):
        raise WorldFileError("nothing was sent")
    monkeypatch.setattr(flow, "fold", broken)
    with pytest.raises(flow.PushStopped, match="landed") as e:
        flow.push(client, c, "My World", **dirs)
    assert "nothing was sent" not in str(e.value).split("(")[0] and client.puts


def test_a_save_right_behind_the_push_stays_a_studio_edit(tmp_path, dirs):
    client = Fake()
    c = do_check(client, write(tmp_path, level=2), dirs)
    real = client.replace

    def racing(world, etag):
        new = real(world, etag)
        client.world["initialGameState"]["npcs"]["Ann"]["level"] = 9
        client.etag = '"studio"'
        return new
    client.replace = racing
    assert flow.push(client, c, "My World", **dirs).raced
    client.replace = real
    assert [d[3] for d in do_check(client, write(tmp_path, level=3), dirs).studio_edits] == [9]


@pytest.mark.parametrize("error, words", [(ApiError(503, "studio_unavailable", "x"), "nothing changed"), (ApiError(0, "too_large", "x"), "nothing changed"),
                                          (ValueError("odd"), "may or may not")])
def test_each_failed_write_is_told_as_it_is(tmp_path, dirs, error, words):
    client = Fake()
    c = do_check(client, write(tmp_path, level=2), dirs)
    client.fail_put = error
    with pytest.raises(flow.PushStopped, match=words):
        flow.push(client, c, "My World", **dirs)


def test_a_backup_of_another_world_is_blocked(tmp_path, dirs):
    f = tmp_path / "b.json"
    f.write_text(json.dumps({"etag": "x", "world": {"shortId": "other", "initialGameState": {**STATE, "npcs": {"Ann": {"level": 5}}}}}))
    assert any("different world" in b for b in do_check(Fake(), f, dirs).blocked)


def test_a_top_level_data_key_does_not_swallow_the_world_and_duplicates_refuse(tmp_path):
    f = tmp_path / "x.json"
    f.write_text(json.dumps({**STATE, "data": {"heroesVersion": 37}}))
    assert "npcs" in read_state(f)
    f.write_text('{"heroesVersion": 37, "npcs": {"Ann": {}, "Ann": {"level": 2}}}')
    with pytest.raises(WorldFileError, match="twice"):
        read_state(f)


def test_a_broken_emoji_is_named(tmp_path):
    f = tmp_path / "x.json"
    f.write_text('{"heroesVersion": 37, "t": "\\ud83d"}')
    with pytest.raises(WorldFileError, match="emoji"):
        read_state(f)


def test_voyage_refilling_its_own_fields_is_not_a_change():
    live = {"unassignedAreas": None, "itemSettings": {"tiers": {"a": 1}, "keep": 1}, "npcs": {"A": {"detailType": "detailed", "gone": 1}}}
    ours = {"unassignedAreas": {}, "itemSettings": {"keep": 1}, "npcs": {"A": {}}}
    from world_push.worldfile import real_changes
    assert [d[1] for d in real_changes(live, ours)] == [["npcs", "A", "gone"]]


def test_voyages_own_quest_triggers_in_an_export_are_not_counted_twice(tmp_path, dirs):
    state = copy.deepcopy(STATE)
    story = {"type": "story", "query": "done"}
    state["questTriggers"] = {f"__generated_quest_progress__/q{i}": {"conditions": [story], "effects": []} for i in range(flow.SEMANTIC_CAP + 1)}
    state["quests"] = {"One": {"detailType": "detailed", "completionCondition": story}}
    c = do_check(Fake(), write(tmp_path, state, level=2), dirs)
    assert not [f for f in c.findings if "quest checks once saved" in f.title]
    assert any(n.startswith("AI-judged triggers: 0 of 500") and "once saved: 1 of 500 (1 of them built by Voyage" in n for n in c.notes)


def test_publish_reads_no_when_this_app_finds_a_publish_blocker(tmp_path, dirs):
    state = copy.deepcopy(STATE)
    story = {"type": "story", "query": "x"}
    state["questTriggers"] = {f"q{i}": {"conditions": [story], "effects": [{"type": "story", "instruction": str(i)}]} for i in range(flow.SEMANTIC_CAP)}
    state["quests"] = {"One": {"completionCondition": story}}   # no detailType counts as detailed
    c = do_check(Fake(), write(tmp_path, state, level=2), dirs)
    assert c.publish["valid"] and not c.can_publish


def test_premades_studio_wiped_after_a_push_show_on_the_next_check(tmp_path, dirs):
    state = copy.deepcopy(STATE)
    state["premadeCharacters"] = [{"name": n, "description": f"{n}'s own long enough story text"} for n in ("Ann", "Bo", "Cy")]
    client = Fake(state)
    f = write(tmp_path, state, level=2)
    flow.push(client, do_check(client, f, dirs), "My World", **dirs)
    client.world["initialGameState"]["premadeCharacters"] = client.world["initialGameState"]["premadeCharacters"][:1]   # Studio's wipe
    client.etag = '"wiped"'
    c = do_check(client, write(tmp_path, state, level=3), dirs)
    [lost] = [x for x in c.findings if x.title == "Premade characters missing from the live draft"]
    assert {w for w, _ in lost.items} == {"Premade character: Bo", "Premade character: Cy"}


def test_an_ending_studio_adds_after_a_push_shows_on_the_next_check(tmp_path, dirs):
    client = Fake()
    f = write(tmp_path, level=2)
    flow.push(client, do_check(client, f, dirs), "My World", **dirs)
    client.world["initialGameState"]["triggers"] = {"wrap": {"conditions": [{"type": "game-tick", "operator": "greaterThan", "value": 99}],
                                                             "effects": [{"type": "end-game"}]}}   # the assistant's quiet ending
    client.etag = '"studio"'
    c = do_check(client, write(tmp_path, level=3), dirs)
    [f] = [x for x in c.findings if x.title == "Studio added a way for the game to end"]
    assert f.items == [("Trigger: wrap", "ends the game for everyone. Your file doesn't.")]
