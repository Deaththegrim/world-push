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
