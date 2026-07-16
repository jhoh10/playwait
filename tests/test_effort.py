from playwait.effort import cooldown_seconds_for_effort, score_effort


def test_low_effort_yes() -> None:
    assert score_effort("yes") == 0.0
    assert score_effort("ok") == 0.0
    assert score_effort("1") == 0.0


def test_short_reply_low() -> None:
    s = score_effort("sounds good")
    assert 0.0 < s <= 0.25


def test_long_thoughtful_higher() -> None:
    prompt = """
I'd rather we keep heuristics for now because an LLM call on every send
adds latency and leaks prompts. Please implement scoring on length,
code fences, and decision language, then map to cool-down seconds.

Also make sure multi-chat takes the peak effort across replies.
""".strip()
    s = score_effort(prompt)
    assert s >= 0.45


def test_code_fence_boosts() -> None:
    plain = score_effort("here is a small change to try")
    with_code = score_effort("try this:\n```\nprint(1)\n```\n")
    assert with_code > plain


def test_cooldown_scale_30_to_180() -> None:
    assert cooldown_seconds_for_effort(0.0, minimum=30, maximum=180) == 30
    assert cooldown_seconds_for_effort(1.0, minimum=30, maximum=180) == 180
    mid = cooldown_seconds_for_effort(0.5, minimum=30, maximum=180)
    assert 100 <= mid <= 110
