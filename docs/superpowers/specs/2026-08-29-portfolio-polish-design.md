# Portfolio Polish Design

## Goal

Make Meowsage safer and more polished as a public portfolio project by bounding
user-supplied cat names, correcting stale testing documentation, and refreshing
the GitHub repository description.

## Scope

This change will:

- limit cat names to 32 Unicode code points after surrounding whitespace is
  removed;
- require names to stay on one line and reject control characters;
- keep Unicode, emoji, spaces, and punctuation available;
- apply the same rules to first-run setup, `meow rename`, saved profiles, and
  legacy profile migration;
- correct the README's statement that the project has no tests; and
- update the GitHub repository description to match current Claude Code and
  Codex support.

This change will not add a profanity filter, a custom speech editor, or any
network publishing behavior.

## Name Validation

`meowsage/profile.py` will own the validation rule because every cat name flows
through the profile layer. It will expose `MAX_NAME_LENGTH = 32` and a small
`validate_name(name)` function that returns the normalized valid name or raises
`ValueError` with a stable, user-facing explanation.

A valid name:

- is a string;
- is non-empty after leading and trailing whitespace is removed;
- is no longer than 32 Python Unicode code points after trimming;
- contains no Unicode control characters (`Cc`); and
- contains no Unicode surrogate code points (`Cs`), line separators (`Zl`), or
  paragraph separators (`Zp`).

Format characters such as the zero-width joiner remain allowed so that common
emoji sequences and international names continue to work. Internal spaces and
punctuation are preserved.

Validation examines the original string for forbidden Unicode categories
*before* trimming, so a leading or trailing tab/newline cannot disappear and
be accepted accidentally. It then strips ordinary surrounding whitespace,
checks for an empty result, and enforces the 32-code-point limit. Errors use
one of four stable messages: the value must be text, the name cannot be empty,
the name must be 32 characters or fewer, or the name must stay on one line and
contain no control characters.

### Data flow

- First-run setup treats a blank answer as the existing default name. A
  non-blank invalid answer displays the validation message and asks again.
- `meow rename <name>` validates once. Invalid argument-based input displays
  the validation message and returns without saving. Prompted rename retries
  after invalid input; EOF or a blank answer leaves the current profile
  unchanged. An invalid rename never creates a default profile when none
  exists; a valid rename may create the profile as it does today.
- `save()` validates before writing JSON, assigns the returned normalized value
  back to `profile.name`, and then writes that same value. The caller's in-memory
  profile and the saved profile therefore cannot diverge.
- `load()` accepts only a JSON object. A missing `name` keeps the existing
  backwards-compatible `Meowsage` default, while `null`, a non-string value,
  an invalid name, a malformed/non-object JSON root, or invalid text encoding
  returns `None`. Unknown extra fields are ignored. A valid loaded profile
  contains the normalized value returned by `validate_name()`.
- Legacy migration applies the same schema and validation behavior. A valid
  legacy name is normalized, saved, and returned consistently; invalid legacy
  data returns `None` and is not migrated.
- `load()` itself never rewrites invalid current-profile data. If a later
  interactive launch completes setup with a valid name, the normal `save()`
  step intentionally replaces that invalid file. A non-interactive launch
  continues to use the unsaved default-name fallback.

Validation errors are handled at interactive boundaries and do not produce a
traceback. File-system errors retain their existing behavior.

## Tests

Tests will be written before production changes in a new
`tests/test_profile.py`. They will cover:

- ordinary ASCII, Unicode, emoji, spaces, and punctuation;
- surrounding-whitespace trimming;
- the 32-character boundary and rejection at 33 characters;
- forbidden characters at the start, middle, and end of input, including
  newline, tab, Unicode line/paragraph separator, and lone surrogate rejection;
- non-object JSON roots, missing names, `null`, invalid text encoding, and
  invalid persisted names, including verification that `load()` itself does
  not rewrite the file;
- `save()` refusing invalid names;
- first-run setup asking again after an invalid answer; and
- argument-based and prompted rename behavior, including preservation of the
  previous name and no profile creation after invalid input; and
- valid and invalid legacy-profile migration.

The complete pytest suite will run after the change. No Qt display is needed
because validation stays in the profile/CLI layer.

## Documentation and Repository Metadata

The README's testing section will state that pytest and GitHub Actions cover
the pure mood, usage-scoring, profile, and name-validation logic, while
`scripts/check_sizing.py` remains the headless GUI-oriented smoke check. The
adjacent GitHub Actions workflow comment will be updated to list the newly
tested profile/CLI modules so repository documentation stays internally
consistent.

After the versioned changes pass, the GitHub repository description will be
updated to:

> A pixel-art desktop cat whose mood and behavior react to your Claude Code and
> Codex activity.

The description update is repository metadata, so it will be applied through
GitHub rather than represented in a tracked file.

## Success Criteria

- Every path that persists or displays a cat name enforces the same 32-character,
  single-line rule.
- Invalid input never overwrites a valid existing profile or crashes launch.
- Normalized names are identical in memory, on disk, and in returned profiles.
- International names and emoji remain supported.
- The README no longer claims there is no test suite.
- The full test suite passes.
- The GitHub description accurately names both supported coding tools, and a
  post-update read verifies the description on the intended repository.
