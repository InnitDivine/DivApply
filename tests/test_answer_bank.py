from __future__ import annotations

from divapply.apply.answers import add_answer, load_answer_bank, match_answers, render_answer_bank_for_prompt


def test_answer_bank_adds_and_matches(tmp_path) -> None:
    path = tmp_path / "answers.yaml"

    add_answer("How many years of Python experience do you have?", "2 years.", path=path)
    entries = load_answer_bank(path)
    matches = match_answers("Years using Python?", path=path)

    assert len(entries) == 1
    assert matches[0]["answer"] == "2 years."


def test_answer_bank_render_prompt_block(tmp_path) -> None:
    path = tmp_path / "answers.yaml"
    add_answer("Are you authorized to work?", "Yes.", path=path)

    rendered = render_answer_bank_for_prompt(path)

    assert "Are you authorized to work?" in rendered
    assert "Yes." in rendered
