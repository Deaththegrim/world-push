import pytest

from world_push.explain import plain_place, plain_size


@pytest.mark.parametrize("path, words", [   # Voyage's own paths, from a real /validate answer
    ("$.npcs.Ann", "NPC: Ann"),
    ('$.npcs["Rena Kurosawa"].type', "NPC: Rena Kurosawa (type)"),
    ("$.npcs.Doge.inventory", "NPC: Doge (inventory)"),
    ('$.parties[""].quests["Find the Gate"].rewardXp', "Quest: Find the Gate (rewardXp)"),
    ('$.storyStarts["The Gate"].startingItems[4].item', "Story start: The Gate (startingItems[4].item)"),
    ('$.worldLore["Old War"].name', "Lore entry: Old War (name)"),
    ('$.npcs["Dr. Who"]', "NPC: Dr. Who"),
])
def test_a_place_reads_as_words(path, words):
    assert plain_place(path) == words


def test_a_place_it_does_not_know_stays_as_voyage_wrote_it():
    assert plain_place("$.somethingNew.Ann") == "somethingNew.Ann"
    assert plain_place("$.narratorStyle") == "narratorStyle"
    assert plain_place("$.npcs") == "npcs"
    assert plain_place("npcs > Ann > worldVoiceId") == "npcs > Ann > worldVoiceId"
    assert plain_place("") == ""


def test_over_both_limits_gives_both_cuts():
    message = ('NPC "Ann" exceeds the 12,000 character limit by 57 characters. '
               'To publish: NPC "Ann" exceeds the 8,000 character limit by 4,057 characters')
    assert plain_size(message, "error") == "This is 12,057 characters. Cut 57 characters to save it as a draft (limit 12,000). Cut 4,057 characters to publish it (limit 8,000)."


def test_over_the_publish_limit_only_says_the_one_cut():
    message = 'NPC "Ann" exceeds the 8,000 character limit by 1 character'
    assert plain_size(message, "publish") == "This is 8,001 characters. Cut 1 character to publish it (limit 8,000)."


def test_a_limit_warning_tells_nobody_to_cut_anything():
    message = 'NPC "Ann" exceeds the 8,000 character limit by 9 characters'
    assert plain_size(message, "warning") == "This is 8,009 characters. The limit is 8,000."


def test_a_refusal_with_one_limit_only_says_the_one_cut():
    message = 'NPC "Ann" exceeds the 8,000 character limit by 9 characters'
    assert plain_size(message, "error") == "This is 8,009 characters. Cut 9 characters to save it (limit 8,000)."


def test_a_message_with_no_character_limit_gets_no_size_line():
    assert plain_size("Story starts exceeds the limit of 152 by 301", "error") is None
    assert plain_size("", "error") is None


@pytest.mark.parametrize("code, message, title", [   # real /validate messages, 2026-11-09 sweep of his worlds
    ("game-state.invariant.invalid-reference", 'triggerDefinitions.nb_bout_a_open references missing areas "Bell Ring".', "Trigger watching a place that doesn't exist"),
    ("game-state.invariant.invalid-reference", 'triggerDefinitions.warp_crossing_detour references missing locations "Warp Current: ".', "Trigger watching a place that doesn't exist"),
    ("game-state.invariant.invalid-reference", 'Invalid questLocation "Spaceship Crash Site" at parties >  > quests > Zee > questLocation. Allowed IDs: A, B',
     "Reference to something that doesn't exist"),
    ("game-state.invariant.invalid-reference",   # 2026-11-09 probe: Voyage only warns, and the effect does nothing in play
     'triggerDefinitions.A Bizarre Adventure Discovery references missing objectives in the selected quest "no_such_objective".',
     "Trigger pointing at a quest or objective that doesn't exist"),
    ("game-state.invariant.invalid-reference", 'triggerDefinitions.A Bizarre Adventure Discovery references missing quests "No Such Quest".',
     "Trigger pointing at a quest or objective that doesn't exist"),
    ("game-state.invariant.invalid-choice", 'Slot "consumable" is for category "Consumable", but item category is "Berry".', "Item in a slot meant for another category"),
    ("game-state.invariant.invalid-choice", 'Invalid attribute "charisma" at skills > intimidation > attribute. Allowed IDs: agility, fellowship.',
     "Value that isn't one of the choices"),
])
def test_each_type_met_in_real_worlds_gets_its_own_advice(code, message, title):
    from world_push.findings import _rule
    assert _rule(code, message)[0] == title


def test_a_trigger_place_reads_as_words():
    assert plain_place("$.triggerDefinitions.nb_bout_a_open.conditions[0].value") == "Trigger: nb_bout_a_open (conditions[0].value)"


def finding():
    from world_push.findings import Finding
    return Finding("warning", "NPC with no area", "no area set", "pick one of the location's rooms",
                   [('$.npcs["Ann Lee"].currentArea', "Ann Lee has no area"), ("$.npcs.Bo.currentArea", "Bo has no area")])


def test_the_filter_keeps_matching_places_or_the_whole_problem():
    from world_push.explain import matches
    f = finding()
    assert matches(f, "error", "") == []
    assert matches(f, None, "") == f.items == matches(f, "warning", "  ")
    assert matches(f, None, "ann lee") == [f.items[0]]             # the plain place
    assert matches(f, None, "npcs.bo") == [f.items[1]]             # Voyage's own path
    assert matches(f, None, "Location's ROOMS") == f.items         # the advice holds it, in no place or message
    assert matches(f, None, "zzz") == []


def test_the_report_holds_every_place_and_the_verdict():
    from types import SimpleNamespace
    from world_push.explain import report
    c = SimpleNamespace(title="My World", short_id="abc", blocked=["Fix the errors."], notes=[], draft={"valid": False}, can_publish=False,
                        changes=[("added", ["abilities", "Iron Fist"], None, {}), ("changed", ["npcs", "Ann", "age"], 1, 2)], studio_edits=[], findings=[finding()])
    text = report(c, "w.json", "9.9", "2026-11-09 10:00")
    assert "World: My World [abc]" in text and "Save as a draft: no. Publish: no." in text and "Can't push: Fix the errors." in text
    assert "What a push changes:\n  Abilities: 1 added (Iron Fist)\n  NPCs: 1 changed (Ann)" in text
    assert "Warning: NPC with no area (2)" in text and "  - NPC: Ann Lee (currentArea): Ann Lee has no area" in text and "NPC: Bo (currentArea)" in text


def test_the_change_summary_counts_records_and_names_them():
    from world_push.explain import summarize
    ch = [("added", ["abilities", "Iron Fist"], None, {}), ("added", ["abilities", "Guard"], None, {}), ("changed", ["npcs", "Ann", "age"], 1, 2),
          ("changed", ["npcs", "Ann", "type"], "a", "b"), ("added", ["npcs", "Bo"], None, {}), ("removed", ["skills", "old"], {}, None),
          ("changed", ["narratorStyle"], "a", "b")] + [("added", ["worldLore", f"e{i}"], None, "x") for i in range(8)]
    assert summarize(ch) == ["Lore entries: 8 added (e0, e1, e2, e3, e4, e5 and 2 more)", "Abilities: 2 added (Iron Fist, Guard)",
                             "NPCs: 1 added (Bo); 1 changed (Ann)", "Skills: 1 removed (old)", "narratorStyle: changed"]
