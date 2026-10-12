"""A base no name describes, so nothing is recorded and the entry is not a candidate."""

from tests.typed_candidate_cases.t01_base import Shape


def _pick_base() -> type:
    return Shape


Computed = type("Computed", (_pick_base(),), {"area": lambda self: 6})
