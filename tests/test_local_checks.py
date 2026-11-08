from world_push.findings import SEMANTIC_CAP, budgets, duplicate_triggers, local_checks

STORY = {"type": "story", "query": "the party rests"}
TICK = {"type": "game-tick", "operator": "greaterThan", "value": 0}


def trig(name, conds, effects=()):
    return {"name": name, "recurring": False, "conditions": list(conds), "effects": list(effects)}


def quest(story=True, detail="detailed"):
    return {"detailType": detail, "completionCondition": {"type": "story", "query": "done" if story else " "}}


def test_budgets_count_the_quest_checks_voyage_builds_on_save():
    st = {"triggers": {"a": trig("a", [STORY]), "b": trig("b", [TICK])}, "questTriggers": {"q": trig("q", [{"type": "action", "query": "x"}])},
          "quests": {"one": quest(), "blank": quest(story=False), "brief": quest(detail="brief")}}
    assert budgets(st) == (1, 2, 1)


def test_over_the_quest_budget_only_after_save_is_a_publish_blocker():
    st = {"questTriggers": {f"q{i}": trig(f"q{i}", [STORY], [{"type": "story", "instruction": str(i)}]) for i in range(SEMANTIC_CAP)},
          "quests": {"one": quest()}}
    [f] = [f for f in local_checks(st) if f.severity == "publish"]
    assert "501" in f.wrong and "can't see this" in f.wrong
    st["quests"] = {}
    assert not [f for f in local_checks(st) if f.severity == "publish"]   # exactly at the cap, and Voyage reports a real overrun itself


def test_a_copied_trigger_is_found_in_either_section_and_condition_order_does_not_hide_it():
    st = {"triggers": {"a": trig("a", [STORY, TICK], [{"type": "x"}])}, "questTriggers": {"b": trig("b", [TICK, STORY], [{"type": "x"}])}}
    [f] = duplicate_triggers(st)
    assert f.title == "The same trigger more than once" and [w for w, _ in f.items] == ["Trigger: a", "Quest trigger: b"]


def test_a_repeated_ai_question_is_found_and_mechanical_twins_are_normal():
    st = {"triggers": {"a": trig("a", [STORY], [{"type": "x"}]), "b": trig("b", [STORY], [{"type": "y"}]),
                       "c": trig("c", [TICK], [{"type": "x"}]), "d": trig("d", [TICK], [{"type": "y"}])}}
    [f] = duplicate_triggers(st)
    assert f.title.startswith("The same AI-judged question") and {w for w, _ in f.items} == {"Trigger: a", "Trigger: b"}


def test_a_long_list_of_twins_is_cut_short():
    st = {"triggers": {f"t{i}": trig(f"t{i}", [STORY], [{"type": str(i)}]) for i in range(9)}}
    assert duplicate_triggers(st)[0].items[0][1].endswith("and 4 more")


def test_a_malformed_world_never_stops_the_local_checks():
    for bad in ([], "x", 3, None, {"a": "x"}, {"a": {"conditions": "x"}}, {"a": {"conditions": [None, "x", {"type": ["story"]}]}}):
        st = {"triggers": bad, "questTriggers": bad, "quests": bad, "npcs": bad, "aiInstructions": bad, "worldVoices": bad}
        local_checks(st)
        budgets(st)
    st = {"quests": {"q": {"completionCondition": {"type": "story", "query": 3}}}, "npcs": {"a": {"worldVoiceId": ["x"]}},
          "aiInstructions": {"generateDialogue": "text"}}
    assert budgets(st) == (0, 0, 0) and local_checks(st) == []


def test_two_pairs_of_copies_on_one_ai_question_are_both_kinds_of_problem():
    st = {"triggers": {"a": trig("a", [STORY], [{"type": "x"}]), "b": trig("b", [STORY], [{"type": "x"}]),
                       "c": trig("c", [STORY], [{"type": "y"}]), "d": trig("d", [STORY], [{"type": "y"}])}}
    titles = [f.title for f in duplicate_triggers(st)]
    assert titles == ["The same trigger more than once", "The same AI-judged question asked more than once"]


def pm(name, text="a long enough backstory for this premade character"):
    return {"name": name, "description": text, "traits": ["Fighter"], "portraitUrl": f"https://x/{name}.webp"}


def test_a_push_that_drops_premades_says_which():
    from world_push.findings import premade_checks
    live = {"premadeCharacters": [pm("Ann", "a"), pm("Bo", "b"), pm("Cy", "c")]}
    ours = {"premadeCharacters": [pm("Ann", "a")]}
    [f] = premade_checks(live, ours)
    assert f.title == "This push removes premade characters" and [w for w, _ in f.items] == ["Premade character: Bo", "Premade character: Cy"]


def test_premades_studio_lost_since_the_last_push_and_whether_the_file_restores_them():
    from world_push.findings import premade_checks
    last = {"premadeCharacters": [pm("Ann", "a"), pm("Bo", "b"), pm("Cy", "c")]}
    live = {"premadeCharacters": [pm("Ann", "a")]}
    ours = {"premadeCharacters": [pm("Ann", "a"), pm("Bo", "b")]}
    [f] = premade_checks(live, ours, last)
    assert f.title == "Premade characters missing from the live draft"
    assert f.items == [("Premade character: Bo", "Your file has it, so a push puts it back."), ("Premade character: Cy", "Your file doesn't have it either.")]
    assert premade_checks(live, ours, None) == []   # no record of a last push: nothing to compare


def test_premades_overwritten_with_one_text_are_found_but_different_portraits_do_not_hide_it():
    from world_push.findings import premade_checks
    ours = {"premadeCharacters": [pm("Ann"), pm("Bo"), pm("Cy", "her own very different and long enough story")]}
    [f] = premade_checks(ours, ours)
    assert f.title == "Premade characters that read exactly the same" and {w for w, _ in f.items} == {"Premade character: Ann", "Premade character: Bo"}


def test_malformed_premades_never_stop_a_check():
    from world_push.findings import premade_checks
    for bad in (None, "x", {"a": 1}, [None, "x", 3, {"name": None}, {}]):
        premade_checks({"premadeCharacters": bad}, {"premadeCharacters": bad}, {"premadeCharacters": bad})
    assert premade_checks([], "x", 3) == []


END = {"type": "end-game", "endScope": "players", "othersOutcome": "won"}


def ends(where="triggers", **extra):
    if where == "quests":
        return {"quests": {"Q": {"onCompleteEffects": [END]}}, **extra}
    return {where: {"finale": trig("finale", [TICK], [END])}, **extra}


def test_endings_are_found_in_triggers_quest_triggers_and_quest_effects_and_described():
    from world_push.findings import _endings
    assert dict(_endings(ends())) == {("Trigger: finale", "ends the game for the players who meet it; the others have won"): 1}
    assert [p for p, _ in _endings(ends("questTriggers"))] == ["Quest trigger: finale"]
    assert [p for p, _ in _endings(ends("quests"))] == ["Quest: Q"]
    assert dict(_endings({"triggers": {"x": trig("x", [TICK], [{"type": "end-game"}])}})) == {("Trigger: x", "ends the game for everyone"): 1}
    assert not _endings({"endGame": {"win": {"endCondition": "win"}}})   # the closing words alone end nothing


def test_a_win_and_a_loss_are_endings_too():
    from world_push.findings import _endings
    st = {"triggers": {"w": trig("w", [TICK], [{"type": "win-game"}]), "l": trig("l", [TICK], [{"type": "lose-game", "endScope": "players"}])}}
    assert set(_endings(st)) == {("Trigger: w", "ends the game as a win for everyone"), ("Trigger: l", "ends the game as a loss for the players who meet it")}


def test_a_second_ending_in_one_trigger_or_one_widened_to_everyone_reads_as_new():
    from world_push.findings import ending_checks
    one = {"triggers": {"t": trig("t", [TICK], [{"type": "end-game", "endScope": "players"}])}}
    two = {"triggers": {"t": trig("t", [TICK], [{"type": "end-game", "endScope": "players"}, {"type": "end-game", "endScope": "players"}])}}
    wide = {"triggers": {"t": trig("t", [TICK], [{"type": "end-game"}])}}
    assert [f.title for f in ending_checks(one, two)] == ["This push adds a way for the game to end"]
    [f] = ending_checks(one, wide)
    assert f.items == [("Trigger: t", "ends the game for everyone")]
    [f] = ending_checks(two, two, one)
    assert f.title == "Studio added a way for the game to end" and f.items[0][1].endswith("Your file has it too.")


def test_an_ending_studio_added_since_the_last_push_is_flagged_and_says_whether_the_file_keeps_it():
    from world_push.findings import ending_checks
    [f] = ending_checks(ends(), {}, {})
    assert f.title == "Studio added a way for the game to end" and f.items[0][1].endswith("Your file doesn't.")
    titles = [x.title for x in ending_checks(ends(), ends(), {})]
    assert titles == ["Studio added a way for the game to end"] and ending_checks(ends(), ends(), {})[0].items[0][1].endswith("Your file has it too.")
    assert ending_checks(ends(), ends(), None) == []        # no record of a last push
    assert ending_checks(ends(), ends(), ends()) == []      # it was there when we last pushed: nobody added it


def test_a_push_that_adds_an_ending_says_so_and_a_world_that_already_ends_is_quiet():
    from world_push.findings import ending_checks
    [f] = ending_checks({}, ends())
    assert f.title == "This push adds a way for the game to end"
    assert ending_checks(ends(), ends()) == []
    for bad in (None, "x", {"triggers": "x"}, {"triggers": {"a": "x"}}):
        ending_checks(bad, bad, bad)


def test_two_premades_with_one_name_cannot_hide_a_deletion():
    from world_push.findings import premade_checks
    live = {"premadeCharacters": [pm("Vex", "first long enough story for this one"), pm("Vex", "second long enough story for that one")]}
    ours = {"premadeCharacters": [pm("Vex", "first long enough story for this one")]}
    [f] = premade_checks(live, ours)
    assert f.items == [("Premade character: Vex", "In the live draft, not in your file (1 of the 2 with this name).")]
    [f] = premade_checks(ours, ours, live)
    assert f.title == "Premade characters missing from the live draft" and f.items[0][1].startswith("Your file doesn't have it either.")


def test_an_unnamed_premade_moved_in_the_list_is_not_a_deletion_but_a_changed_one_is():
    from world_push.findings import premade_checks
    a, b = {"description": "nameless one with a long enough text"}, {"description": "nameless two with a long enough text"}
    assert premade_checks({"premadeCharacters": [a, b]}, {"premadeCharacters": [b, a]}) == []
    [f] = premade_checks({"premadeCharacters": [a, b]}, {"premadeCharacters": [a, {"description": "a different text entirely"}]})
    assert f.title == "This push removes premade characters" and f.items[0][0].startswith("Premade character: (no name: ")
