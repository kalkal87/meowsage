"""CLI interaction tests."""

import json

import pytest

from meowsage import cli, profile


@pytest.fixture(autouse=True)
def isolated_profile_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(profile, "_PROFILE_DIR", tmp_path / "meowsage")
    monkeypatch.setattr(profile, "_PROFILE_PATH", tmp_path / "meowsage" / "profile.json")
    monkeypatch.setattr(profile, "_LEGACY_PROFILE_PATH", tmp_path / "usage-pet" / "profile.json")


def _save(name="Sprite"):
    profile.save(profile.Profile(name))


def test_argument_rename_normalizes_persists_and_prints(capsys):
    cli._rename([" ", "Luna", " "])

    assert profile.load().name == "Luna"
    assert capsys.readouterr().out == "meow: renamed to Luna.\n"


def test_argument_overlong_name_keeps_existing_profile(capsys):
    _save()

    cli._rename(["a" * 33])

    assert profile.load().name == "Sprite"
    assert capsys.readouterr().out == (
        "meow: name must be 32 characters or fewer, nothing changed.\n"
    )


def test_argument_trailing_tab_is_rejected_before_trimming(capsys):
    _save()

    cli._rename(["Luna\t"])

    assert profile.load().name == "Sprite"
    assert capsys.readouterr().out == (
        "meow: name must stay on one line and contain no control characters, nothing changed.\n"
    )


def test_invalid_argument_without_profile_does_not_create_one(capsys):
    cli._rename(["a" * 33])

    assert not profile._PROFILE_PATH.exists()
    assert capsys.readouterr().out.endswith("nothing changed.\n")


def test_prompted_rename_retries_invalid_input(monkeypatch, capsys):
    _save()
    monkeypatch.setattr(profile, "can_prompt", lambda: True)
    answers = iter(["Luna\nCat", "  Luna  "])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    cli._rename([])

    assert profile.load().name == "Luna"
    output = capsys.readouterr().out
    assert "meow: name must stay on one line and contain no control characters; try again.\n" in output
    assert output.endswith("meow: renamed to Luna.\n")


def test_prompted_whitespace_keeps_existing_profile_and_says_nothing_changed(monkeypatch, capsys):
    _save()
    monkeypatch.setattr(profile, "can_prompt", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "   ")

    cli._rename([])

    assert profile.load().name == "Sprite"
    assert capsys.readouterr().out == "meow: name can't be empty, nothing changed.\n"


def test_prompted_whitespace_without_existing_profile_does_not_create_one(monkeypatch, capsys):
    monkeypatch.setattr(profile, "can_prompt", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "   ")

    cli._rename([])

    assert not profile._PROFILE_PATH.exists()
    assert capsys.readouterr().out == "meow: name can't be empty, nothing changed.\n"


def test_prompted_eof_keeps_existing_profile_and_says_nothing_changed(monkeypatch, capsys):
    _save()
    monkeypatch.setattr(profile, "can_prompt", lambda: True)

    def raise_eof(_prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)

    cli._rename([])

    assert profile.load().name == "Sprite"
    assert capsys.readouterr().out == "\nmeow: name can't be empty, nothing changed.\n"


def test_prompted_eof_without_existing_profile_does_not_create_one(monkeypatch, capsys):
    monkeypatch.setattr(profile, "can_prompt", lambda: True)

    def raise_eof(_prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)

    cli._rename([])

    assert not profile._PROFILE_PATH.exists()
    assert capsys.readouterr().out == "\nmeow: name can't be empty, nothing changed.\n"


def test_rename_without_terminal_exits_without_creating_profile(monkeypatch, capsys):
    monkeypatch.setattr(profile, "can_prompt", lambda: False)

    with pytest.raises(SystemExit) as exc_info:
        cli._rename([])

    assert exc_info.value.code == 1
    assert not profile._PROFILE_PATH.exists()
    assert capsys.readouterr().out == "meow: no terminal to ask in — try `meow rename <name>`.\n"
