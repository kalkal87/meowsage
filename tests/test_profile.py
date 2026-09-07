"""Profile validation and persistence tests."""

import json

import pytest

from meowsage import profile


@pytest.fixture(autouse=True)
def isolated_profile_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(profile, "_PROFILE_DIR", tmp_path / "meowsage")
    monkeypatch.setattr(profile, "_PROFILE_PATH", tmp_path / "meowsage" / "profile.json")
    monkeypatch.setattr(profile, "_LEGACY_PROFILE_PATH", tmp_path / "usage-pet" / "profile.json")


def test_validate_allows_basic_names_and_strips_surrounding_spaces():
    assert profile.validate_name("Whiskers") == "Whiskers"
    assert profile.validate_name("  Whiskers  ") == "Whiskers"


def test_validate_allows_emoji_and_international_names():
    assert profile.validate_name("🐈") == "🐈"
    assert profile.validate_name("Мурзик") == "Мурзик"


def test_validate_allows_punctuation_internal_spaces_and_zwj():
    assert profile.validate_name("Dr. Whiskers!") == "Dr. Whiskers!"
    assert profile.validate_name("👩‍💻") == "👩‍💻"


def test_validate_allows_exactly_32_characters():
    name = "a" * 32
    assert profile.validate_name(name) == name


def test_validate_rejects_non_string():
    with pytest.raises(ValueError, match="name must be text"):
        profile.validate_name(None)


def test_validate_rejects_whitespace_only():
    with pytest.raises(ValueError, match="name can't be empty"):
        profile.validate_name("   ")


def test_validate_rejects_33_characters():
    with pytest.raises(ValueError, match="name must be 32 characters or fewer"):
        profile.validate_name("a" * 33)


@pytest.mark.parametrize("name", ["\nCat", "Cat\n", "Ca\nt"])
def test_validate_rejects_newline(name):
    with pytest.raises(ValueError, match="name must stay on one line and contain no control characters"):
        profile.validate_name(name)


@pytest.mark.parametrize("name", ["\tCat", "Cat\t", "Ca\tt"])
def test_validate_rejects_tab(name):
    with pytest.raises(ValueError, match="name must stay on one line and contain no control characters"):
        profile.validate_name(name)


def test_validate_rejects_line_separator():
    with pytest.raises(ValueError, match="name must stay on one line and contain no control characters"):
        profile.validate_name("Cat\u2028Name")


def test_validate_rejects_paragraph_separator():
    with pytest.raises(ValueError, match="name must stay on one line and contain no control characters"):
        profile.validate_name("Cat\u2029Name")


def test_validate_rejects_lone_surrogate():
    with pytest.raises(ValueError, match="name must stay on one line and contain no control characters"):
        profile.validate_name("Cat\ud800")


def test_load_valid_object_normalizes_name_and_ignores_extra_fields():
    profile._PROFILE_PATH.parent.mkdir()
    profile._PROFILE_PATH.write_text(json.dumps({"name": "  Luna  ", "mood": "happy"}))
    loaded = profile.load()
    assert loaded.name == "Luna"
    assert not hasattr(loaded, "mood")


def test_load_json_value_error_returns_none(monkeypatch):
    _write_profile_text('{"name":"Luna"}')

    def raising_json_load(stream):
        raise ValueError("integer conversion limit")

    monkeypatch.setattr(profile.json, "load", raising_json_load)
    assert profile.load() is None


def test_load_missing_name_uses_default():
    profile._PROFILE_PATH.parent.mkdir()
    profile._PROFILE_PATH.write_text("{}")
    assert profile.load().name == profile.DEFAULT_NAME


def test_load_malformed_json_returns_none():
    profile._PROFILE_PATH.parent.mkdir()
    profile._PROFILE_PATH.write_text("{not json")
    assert profile.load() is None


def test_load_null_name_returns_none():
    _write_profile_text('{"name": null}')
    assert profile.load() is None


def test_load_invalid_name_returns_none():
    _write_profile_text(json.dumps({"name": "\nCat"}))
    assert profile.load() is None


def test_load_non_object_returns_none():
    _write_profile_text("[]")
    assert profile.load() is None


def test_load_invalid_utf8_returns_none():
    profile._PROFILE_PATH.parent.mkdir()
    profile._PROFILE_PATH.write_bytes(b'{"name":"\xe9"}')
    assert profile.load() is None


def test_load_invalid_file_does_not_rewrite_it():
    raw = b'{"name": null}'
    profile._PROFILE_PATH.parent.mkdir()
    profile._PROFILE_PATH.write_bytes(raw)
    assert profile.load() is None
    assert profile._PROFILE_PATH.read_bytes() == raw


def test_save_normalizes_name_and_writes_utf8_json():
    pet = profile.Profile("  Møuse ")
    profile.save(pet)
    assert pet.name == "Møuse"
    assert json.loads(profile._PROFILE_PATH.read_text(encoding="utf-8"))["name"] == pet.name


def test_save_rejects_invalid_name_before_creating_directory():
    with pytest.raises(ValueError):
        profile.save(profile.Profile("\nCat"))
    assert not profile._PROFILE_DIR.exists()


def test_save_failed_validation_leaves_existing_file_unchanged():
    raw = b'{"name":"Original"}'
    profile._PROFILE_DIR.mkdir()
    profile._PROFILE_PATH.write_bytes(raw)
    with pytest.raises(ValueError):
        profile.save(profile.Profile("\tinvalid"))
    assert profile._PROFILE_PATH.read_bytes() == raw


def test_valid_legacy_profile_is_normalized_saved_and_returned():
    profile._LEGACY_PROFILE_PATH.parent.mkdir()
    profile._LEGACY_PROFILE_PATH.write_text(json.dumps({"name": "  Cleo  "}))
    migrated = profile.load()
    assert migrated.name == "Cleo"
    assert json.loads(profile._PROFILE_PATH.read_text(encoding="utf-8"))["name"] == "Cleo"


def test_invalid_legacy_profile_is_not_migrated():
    raw = json.dumps({"name": "\nCleo"}).encode("utf-8")
    profile._LEGACY_PROFILE_PATH.parent.mkdir()
    profile._LEGACY_PROFILE_PATH.write_bytes(raw)
    assert profile.load() is None
    assert not profile._PROFILE_PATH.exists()
    assert profile._LEGACY_PROFILE_PATH.read_bytes() == raw


def test_load_overlong_name_returns_none():
    _write_profile_text(json.dumps({"name": "a" * 33}))
    assert profile.load() is None


def test_load_whitespace_only_name_returns_none():
    _write_profile_text(json.dumps({"name": "   "}))
    assert profile.load() is None


def test_setup_retries_invalid_name_then_saves_normalized_name(monkeypatch, capsys):
    monkeypatch.setattr(profile, "can_prompt", lambda: True)
    answers = iter(["a" * 33, "Luna"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    result = profile.load_or_run_setup()

    assert result.name == "Luna"
    assert profile.load().name == "Luna"
    assert "That name must be 32 characters or fewer." in capsys.readouterr().out


def test_setup_whitespace_answer_uses_and_saves_default(monkeypatch):
    monkeypatch.setattr(profile, "can_prompt", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "   ")

    result = profile.load_or_run_setup()

    assert result.name == profile.DEFAULT_NAME
    assert profile.load().name == profile.DEFAULT_NAME


def test_setup_eof_returns_unsaved_default(monkeypatch):
    monkeypatch.setattr(profile, "can_prompt", lambda: True)

    def raise_eof(_prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)

    result = profile.load_or_run_setup()

    assert result.name == profile.DEFAULT_NAME
    assert not profile._PROFILE_PATH.exists()


def _write_profile_text(text):
    profile._PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    profile._PROFILE_PATH.write_text(text)
