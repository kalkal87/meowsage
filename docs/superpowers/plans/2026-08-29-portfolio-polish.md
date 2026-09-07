# Portfolio Polish Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce safe 32-character single-line cat names, correct stale testing documentation, and refresh the GitHub repository description.

**Architecture:** Keep validation in `meowsage/profile.py`, the shared boundary for setup, rename, load, save, and legacy migration. CLI code only handles retry/reporting behavior, while tests remain split between profile persistence rules and command interaction rules. Documentation and repository metadata are updated after behavior is green.

**Tech Stack:** Python 3.9+, pytest, standard-library `json`/`unicodedata`, GitHub Actions, GitHub CLI.

**Specification:** `docs/superpowers/specs/2026-08-29-portfolio-polish-design.md`

**Local test prerequisite:** Create `.venv` if needed and install the same
minimal test dependency used by CI:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install pytest
```

All test commands below use `.venv/bin/python -m pytest` so collection and
execution always use the same interpreter.

---

## Chunk 1: Name validation and persistence

### Task 1: Central profile validation

**Files:**
- Create: `tests/test_profile.py`
- Modify: `meowsage/profile.py:18-127`

- [ ] **Step 1: Add the validator tests first**

Create `tests/test_profile.py` with temporary-path isolation and the core
validation cases:

```python
import json

import pytest

from meowsage import profile


@pytest.fixture(autouse=True)
def isolated_profiles(tmp_path, monkeypatch):
    profile_dir = tmp_path / "meowsage"
    monkeypatch.setattr(profile, "_PROFILE_DIR", profile_dir)
    monkeypatch.setattr(profile, "_PROFILE_PATH", profile_dir / "profile.json")
    monkeypatch.setattr(profile, "_LEGACY_PROFILE_PATH", tmp_path / "legacy.json")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Sprite", "Sprite"),
        ("  Luna  ", "Luna"),
        ("Mochi 🐈", "Mochi 🐈"),
        ("猫ちゃん", "猫ちゃん"),
        ("O'Malley!", "O'Malley!"),
        ("👩\u200d💻", "👩\u200d💻"),
        ("x" * 32, "x" * 32),
    ],
)
def test_validate_name_accepts_supported_names(raw, expected):
    assert profile.validate_name(raw) == expected


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (None, "name must be text"),
        ("   ", "name can't be empty"),
        ("x" * 33, "name must be 32 characters or fewer"),
        ("\nLuna", "name must stay on one line"),
        ("Lu\tna", "name must stay on one line"),
        ("Luna\n", "name must stay on one line"),
        ("Luna\u2028Cat", "name must stay on one line"),
        ("Luna\u2029Cat", "name must stay on one line"),
        ("Luna\ud800", "name must stay on one line"),
    ],
)
def test_validate_name_rejects_invalid_values(raw, message):
    with pytest.raises(ValueError, match=message):
        profile.validate_name(raw)
```

- [ ] **Step 2: Run the validator tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_profile.py -v
```

Expected: 16 test cases fail with a missing `validate_name` attribute. The
tests do not reference `MAX_NAME_LENGTH` directly.

- [ ] **Step 3: Implement the minimal validator**

In `meowsage/profile.py`, import `unicodedata` and add:

```python
MAX_NAME_LENGTH = 32

NAME_TYPE_ERROR = "name must be text"
NAME_EMPTY_ERROR = "name can't be empty"
NAME_LENGTH_ERROR = f"name must be {MAX_NAME_LENGTH} characters or fewer"
NAME_CHARACTER_ERROR = (
    "name must stay on one line and contain no control characters"
)

_FORBIDDEN_NAME_CATEGORIES = {"Cc", "Cs", "Zl", "Zp"}


def validate_name(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError(NAME_TYPE_ERROR)
    if any(
        unicodedata.category(character) in _FORBIDDEN_NAME_CATEGORIES
        for character in name
    ):
        raise ValueError(NAME_CHARACTER_ERROR)
    normalized = name.strip()
    if not normalized:
        raise ValueError(NAME_EMPTY_ERROR)
    if len(normalized) > MAX_NAME_LENGTH:
        raise ValueError(NAME_LENGTH_ERROR)
    return normalized
```

- [ ] **Step 4: Run the validator tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_profile.py -v`

Expected: all validator tests pass.

- [ ] **Step 5: Add failing persistence/schema tests**

Append to `tests/test_profile.py`:

```python
def write_profile(payload):
    profile._PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    profile._PROFILE_PATH.write_text(json.dumps(payload), encoding="utf-8")


def test_save_normalizes_profile_in_memory_and_on_disk():
    active = profile.Profile(name="  Luna  ")

    profile.save(active)

    assert active.name == "Luna"
    assert json.loads(profile._PROFILE_PATH.read_text(encoding="utf-8")) == {
        "name": "Luna"
    }


def test_invalid_save_leaves_existing_file_unchanged():
    write_profile({"name": "Sprite"})
    original = profile._PROFILE_PATH.read_bytes()

    with pytest.raises(ValueError, match="32 characters or fewer"):
        profile.save(profile.Profile(name="x" * 33))

    assert profile._PROFILE_PATH.read_bytes() == original


@pytest.mark.parametrize("payload", [[], "Sprite", 42, None, {"name": None}, {"name": []}])
def test_load_returns_none_for_invalid_schema(payload):
    write_profile(payload)

    assert profile.load() is None


def test_load_uses_default_for_missing_name_and_ignores_extra_fields():
    write_profile({"color": "orange"})

    assert profile.load() == profile.Profile(name=profile.DEFAULT_NAME)


def test_load_returns_normalized_profile():
    write_profile({"name": "  Luna  ", "ignored": True})

    assert profile.load() == profile.Profile(name="Luna")


def test_invalid_profile_is_not_rewritten_by_load():
    write_profile({"name": "x" * 33})
    original = profile._PROFILE_PATH.read_bytes()

    assert profile.load() is None
    assert profile._PROFILE_PATH.read_bytes() == original


def test_load_returns_none_for_invalid_text_encoding():
    profile._PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    profile._PROFILE_PATH.write_bytes(b'{"name":"\xe9"}')

    assert profile.load() is None


def test_load_returns_none_for_malformed_json():
    profile._PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    profile._PROFILE_PATH.write_text("{not json", encoding="utf-8")

    assert profile.load() is None


def test_valid_legacy_profile_is_normalized_and_migrated():
    profile._LEGACY_PROFILE_PATH.write_text(
        json.dumps({"name": "  Luna  "}), encoding="utf-8"
    )

    assert profile.load() == profile.Profile(name="Luna")
    assert json.loads(profile._PROFILE_PATH.read_text(encoding="utf-8")) == {
        "name": "Luna"
    }


def test_invalid_legacy_profile_is_not_migrated():
    original = json.dumps({"name": "x" * 33})
    profile._LEGACY_PROFILE_PATH.write_text(original, encoding="utf-8")

    assert profile.load() is None
    assert not profile._PROFILE_PATH.exists()
    assert profile._LEGACY_PROFILE_PATH.read_text(encoding="utf-8") == original
```

- [ ] **Step 6: Run persistence tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_profile.py -v`

Expected: 18 cases pass and 13 fail. Validator, missing-name compatibility,
and malformed-JSON cases are already green; normalization, invalid schema,
encoding, and migration cases fail against the existing persistence code.

- [ ] **Step 7: Centralize profile decoding and validation**

Refactor `meowsage/profile.py` with one path reader:

```python
def _load_profile(path: Path) -> Optional[Profile]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        name = validate_name(data.get("name", DEFAULT_NAME))
    except ValueError:
        return None
    return Profile(name=name)


def load() -> Optional[Profile]:
    if not _PROFILE_PATH.exists():
        return _migrate_legacy_profile()
    return _load_profile(_PROFILE_PATH)
```

Update legacy migration to call `_load_profile(_LEGACY_PROFILE_PATH)`, return
`None` for invalid data, save the valid normalized profile, and retain the
existing `OSError` fallback. Update `save()` so validation occurs before any
directory/file write:

```python
def save(profile: Profile) -> None:
    profile.name = validate_name(profile.name)
    _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    _PROFILE_PATH.write_text(
        json.dumps(asdict(profile), indent=2), encoding="utf-8"
    )
```

- [ ] **Step 8: Run profile tests and the existing suite**

Run:

```bash
.venv/bin/python -m pytest tests/test_profile.py -v
.venv/bin/python -m pytest tests/ -v
```

Expected: all profile tests and all existing tests pass.

- [ ] **Step 9: Commit central validation**

```bash
git add meowsage/profile.py tests/test_profile.py
git commit -m "feat: validate cat names centrally"
```

### Task 2: Setup and rename interaction behavior

**Files:**
- Modify: `tests/test_profile.py`
- Create: `tests/test_cli.py`
- Modify: `meowsage/profile.py:113-127`
- Modify: `meowsage/cli.py:294-314`

- [ ] **Step 1: Add failing first-run interaction tests**

Append to `tests/test_profile.py`:

```python
def test_setup_retries_invalid_name(monkeypatch, capsys):
    answers = iter(["x" * 33, "Luna"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    active = profile._run_setup_wizard()

    assert active == profile.Profile(name="Luna")
    assert "32 characters or fewer" in capsys.readouterr().out


def test_setup_whitespace_only_uses_default(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "   ")

    active = profile._run_setup_wizard()

    assert active == profile.Profile(name=profile.DEFAULT_NAME)


def test_setup_eof_returns_unsaved_default(monkeypatch):
    def raise_eof(_prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)

    active = profile._run_setup_wizard()

    assert active == profile.Profile(name=profile.DEFAULT_NAME)
    assert not profile._PROFILE_PATH.exists()
```

- [ ] **Step 2: Add failing rename interaction tests**

Create `tests/test_cli.py`:

```python
import json

import pytest

from meowsage import cli, profile


@pytest.fixture(autouse=True)
def isolated_profiles(tmp_path, monkeypatch):
    profile_dir = tmp_path / "meowsage"
    monkeypatch.setattr(profile, "_PROFILE_DIR", profile_dir)
    monkeypatch.setattr(profile, "_PROFILE_PATH", profile_dir / "profile.json")
    monkeypatch.setattr(profile, "_LEGACY_PROFILE_PATH", tmp_path / "legacy.json")


def saved_name():
    return json.loads(profile._PROFILE_PATH.read_text(encoding="utf-8"))["name"]


def test_argument_rename_normalizes_creates_and_confirms(capsys):
    cli._rename(["  Luna  "])

    assert saved_name() == "Luna"
    assert capsys.readouterr().out == "meow: renamed to Luna.\n"


def test_argument_rename_rejects_invalid_name_without_overwriting(capsys):
    profile.save(profile.Profile(name="Sprite"))

    cli._rename(["x" * 33])

    assert saved_name() == "Sprite"
    assert "32 characters or fewer" in capsys.readouterr().out


def test_argument_rename_rejects_trailing_control_before_trimming(capsys):
    profile.save(profile.Profile(name="Sprite"))

    cli._rename(["Luna\t"])

    assert saved_name() == "Sprite"
    assert "stay on one line" in capsys.readouterr().out


def test_invalid_rename_does_not_create_profile(capsys):
    cli._rename(["x" * 33])

    assert not profile._PROFILE_PATH.exists()
    assert "32 characters or fewer" in capsys.readouterr().out


def test_prompted_rename_retries_then_saves(monkeypatch, capsys):
    profile.save(profile.Profile(name="Sprite"))
    monkeypatch.setattr(profile, "can_prompt", lambda: True)
    answers = iter(["Luna\nCat", "  Luna  "])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    cli._rename([])

    assert saved_name() == "Luna"
    assert "stay on one line" in capsys.readouterr().out


def test_prompted_blank_rename_keeps_existing_name(monkeypatch, capsys):
    profile.save(profile.Profile(name="Sprite"))
    monkeypatch.setattr(profile, "can_prompt", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "   ")

    cli._rename([])

    assert saved_name() == "Sprite"
    assert "nothing changed" in capsys.readouterr().out


def test_prompted_rename_eof_keeps_existing_name(monkeypatch, capsys):
    profile.save(profile.Profile(name="Sprite"))
    monkeypatch.setattr(profile, "can_prompt", lambda: True)

    def raise_eof(_prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)

    cli._rename([])

    assert saved_name() == "Sprite"
    assert "nothing changed" in capsys.readouterr().out
```

- [ ] **Step 3: Run interaction tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_profile.py tests/test_cli.py -v
```

Expected: 36 cases pass and 5 fail. The retry/rejection cases fail because
setup does not retry and CLI strips or saves invalid input; the blank, EOF, and
valid argument-based characterization cases pass.

- [ ] **Step 4: Implement first-run retry behavior**

Change `_run_setup_wizard()` to loop. Call `validate_name()` on raw input. Treat
`NAME_EMPTY_ERROR` as the existing default-name choice; print other validation
errors and ask again. On EOF, retain the current unsaved default fallback.

The implementation should have this shape:

```python
def _run_setup_wizard() -> Profile:
    print("Welcome to Meowsage!")
    while True:
        try:
            raw_name = input("What should we call your cat? [Meowsage]: ")
        except EOFError:
            print()
            return Profile()
        try:
            name = validate_name(raw_name)
        except ValueError as exc:
            if str(exc) == NAME_EMPTY_ERROR:
                name = DEFAULT_NAME
                break
            print(f"That {exc}.")
            continue
        break
    profile = Profile(name=name)
    save(profile)
    print(f"Nice to meet you, {name}! (Rename anytime with `meow rename`.)")
    return profile
```

- [ ] **Step 5: Implement rename validation and retry behavior**

Refactor `_rename()` so argument input is checked once, prompted input loops,
and no active profile is loaded/created until after validation succeeds. Use
the raw `" ".join(rest)` value or raw `input()` result directly—without
pre-stripping it—as the argument to `profile_store.validate_name()`. Print
`meow: {error}, nothing changed.` for invalid argument input. Prompted invalid
input prints the error and asks again; `NAME_EMPTY_ERROR` or EOF prints the
existing nothing-changed message and returns. Assign the normalized value
returned by `validate_name()` to the profile and use that same normalized value
in the confirmation output.

- [ ] **Step 6: Run interaction tests and the complete suite**

Run:

```bash
.venv/bin/python -m pytest tests/test_profile.py tests/test_cli.py -v
.venv/bin/python -m pytest tests/ -v
```

Expected: all tests pass with no warnings or errors.

- [ ] **Step 7: Commit interaction behavior**

```bash
git add meowsage/profile.py meowsage/cli.py tests/test_profile.py tests/test_cli.py
git commit -m "feat: enforce name limits in setup and rename"
```

## Chunk 2: Portfolio documentation and delivery

### Task 3: Correct public testing documentation

**Files:**
- Modify: `README.md:288-302`
- Modify: `.github/workflows/tests.yml:30-33`

- [ ] **Step 1: Replace the stale README testing statement**

Replace the opening text and command block under `### Testing without a
display` with this exact Markdown:

````markdown
The pytest suite covers the plain-Python mood, usage-scoring, profile and
name-validation logic. GitHub Actions runs it for pushes to `main`, pull
requests targeting `main`, and manual dispatches against Python 3.9 and 3.12.
Install the development dependency and run it with:

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

GUI and timer changes can also be checked by driving the real app headlessly —
Qt's `offscreen` platform runs the whole thing without a visible window:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/check_sizing.py
```
````

Keep the existing paragraph beginning “Construct a `QApplication`” after these
blocks.

- [ ] **Step 2: Update the workflow dependency comment**

Replace lines 30–33 with this exact comment and preserve the intentionally
minimal `pip install pytest` step:

```yaml
      # Only pytest, not the app's PySide6/Qt runtime dependencies: the tests
      # exercise moods.py, usage.py, config.py, profile.py, and the non-Qt CLI
      # paths. Installing Qt here would cost real CI minutes to test something
      # the suite never imports.
```

- [ ] **Step 3: Verify documentation and tests**

Run:

```bash
rg -n "no test suite|moods.py/usage.py/config.py" README.md .github/workflows/tests.yml
.venv/bin/python -m pytest tests/ -v
git diff --check
```

Expected: `rg` prints nothing and exits with status 1 (no matches); status 0
means stale text remains and status 2 means the search failed. Pytest passes,
and `git diff --check` prints nothing.

- [ ] **Step 4: Commit documentation**

```bash
git add README.md .github/workflows/tests.yml
git commit -m "docs: describe current test coverage"
```

### Task 4: Verify branch and deliver the changes

**Files:**
- No tracked files; this task changes repository metadata after versioned work
  is verified.

- [ ] **Step 1: Verify the exact repository and refresh `main`**

Run:

```bash
pwd
git remote get-url origin
gh repo view kalkal87/meowsage --json nameWithOwner,description,defaultBranchRef
git fetch origin main
git merge-base --is-ancestor origin/main HEAD
git status --short --branch
git log --oneline origin/main..HEAD
.venv/bin/python -m pytest tests/ -v
```

Expected: `pwd` is the Meowsage checkout, `origin` is exactly
`https://github.com/kalkal87/meowsage.git`, GitHub reports
`kalkal87/meowsage` with default branch `main`, the branch is
`codex/portfolio-polish`, the ancestry check exits successfully, `git status`
lists no tracked or untracked changes, the intended commits are listed, and
tests pass. Stop before external writes if any repository, remote, branch, or
cleanliness check differs.

- [ ] **Step 2: Update the GitHub description**

Run:

```bash
gh repo edit kalkal87/meowsage --description "A pixel-art desktop cat whose mood and behavior react to your Claude Code and Codex activity."
```

Expected: command exits successfully.

- [ ] **Step 3: Read back the metadata**

Run:

```bash
gh repo view kalkal87/meowsage --json nameWithOwner,description
```

Expected: `description` exactly matches the approved text.

- [ ] **Step 4: Push the verified review branch**

Run:

```bash
git push -u origin codex/portfolio-polish
```

Expected: push succeeds and local branch tracks
`origin/codex/portfolio-polish`.

- [ ] **Step 5: Open the pull request**

Run:

```bash
gh pr create --repo kalkal87/meowsage --base main --head codex/portfolio-polish --title "Polish cat naming and portfolio documentation" --body "Adds centralized 32-character single-line cat-name validation, tests setup/rename/profile persistence, and corrects the stale testing documentation. The repository description is updated separately as GitHub metadata."
```

Expected: command returns a pull request URL without merging it.

- [ ] **Step 6: Verify the pull request**

Run:

```bash
gh pr view --repo kalkal87/meowsage codex/portfolio-polish --json url,state,baseRefName,headRefName
```

Expected: state is `OPEN`, base is `main`, head is
`codex/portfolio-polish`, and the returned URL opens the intended pull request.
