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
