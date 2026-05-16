---
session_id: "session_20260501_mti63v"
branch: "bugfix/#6-registry-cache-staleness"
created_at: "2026-05-01T15:58:54Z"
current_mode: "code"
version: "1.0"
---

## Session Overview

**Branch:** bugfix/#6-registry-cache-staleness
**Started:** 2026-05-01 15:58 UTC
**Current Mode:** code
**Status:** In Progress

## Mode History

| Mode | Entered | Exited | Summary |
|------|---------|--------|---------|
| plan | 15:50 | 15:58 | Reviewed issue #6, proposed Option B fix + dedup guard, user approved |
| code | 15:58 | - | Implementing fix and tests |

## Actions Taken

### 2026-05-01 15:50 - plan mode
- **Task:** Review GH issue #6 (Registry cache staleness on parent-type lookups)
- **Findings:**
  - Confirmed root cause at `sweet_tea/registry.py:109-115` — `register()` only updates `__lookup` slot keyed by exact `class_def`, never ancestor-type slots
  - Confirmed bonus dedup bug — cache append is outside the `if new_entry not in __registry` guard
- **Decision:** User approved Option B (refresh affected cache slots on register) plus folding in the dedup-guard fix in the same commit
- **Plan deliverable:** in-conversation proposal (no separate planning doc)

### 2026-05-01 15:58 - code mode
- Created branch `bugfix/#6-registry-cache-staleness` from main
- Created this session file
- Edited `sweet_tea/registry.py` — Option B fix + moved cache mutation inside dedup guard
- Added 5 regression tests to `tests/test_registry.py`
- Local CI parity verified: black, ruff, mypy, bandit, pytest (78 passed), pyright (0 errors)
- Committed (no AI attribution per user pref): `b98dfde`
- Pushed branch and opened PR #7: https://github.com/snoodleboot-io/sweet_tea/pull/7
- PR closes #6

## Context Summary

Bug: `Registry.typed_entries(lookup_type=T)` caches a filtered list keyed by `T`. `register()` doesn't refresh ancestor-type cache slots, so classes registered after the first `typed_entries(T)` call are invisible to subsequent calls.

Fix (Option B): in `register()`, walk `__lookup_keys` and append `new_entry` to every slot whose `lookup_type is Any` or whose `lookup_type` is a class that `class_def` is a subclass of. Move all cache-mutation inside the existing `if new_entry not in cls.__registry:` dedup guard so re-registers don't double-count.

Tests planned (unittest.TestCase style to match existing file):
1. `test_typed_entries_sees_registrations_made_after_first_query` — core regression
2. `test_typed_entries_with_any_sees_late_registrations` — `Any` special case
3. `test_typed_entries_does_not_double_count_on_re_register` — dedup guard
4. `test_typed_entries_multi_level_hierarchy_late_registration` — MRO walk
5. `test_typed_entries_unrelated_type_not_added_to_other_caches` — negative test

## Notes

- User wants to review the diff before commit — do not stage/commit until explicit approval.
