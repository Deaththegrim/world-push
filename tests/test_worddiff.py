from world_push.worddiff import CONTEXT, MAX_TOKENS, marked

R, A = "R", "A"


def test_one_word_swapped_in_a_long_card_is_marked_and_the_rest_cut():
    words = " ".join(f"w{i}" for i in range(500))
    old, new = f"{words} She hates the sea. {words}", f"{words} She loves the sea. {words}"
    text, gone, came = marked(old, new, R, A)
    assert (gone, came) == (1, 1)
    assert "<span style='R'>hates </span><span style='A'>loves </span>" in text
    assert text.count("…") == 2 and "w100 " not in text and "w250 " not in text
    assert f"w{500 - CONTEXT // 2} " in text   # context kept beside the edit


def test_text_is_escaped_and_newlines_kept():
    text, _, _ = marked("a <b>x</b>\nc", "a <b>y</b>\nc", R, A)
    assert text == "a &lt;b&gt;<span style='R'>x</span><span style='A'>y</span>&lt;/b&gt;<br>c"


def test_non_text_values_and_too_long_values():
    text, gone, came = marked(3, 4, R, A)
    assert (gone, came) == (1, 1)
    assert marked({"x": [1, 2]}, {"x": [1, 3]}, R, A)[2] == 1
    big = "x " * MAX_TOKENS
    assert marked(big, big + "y", R, A) is None
