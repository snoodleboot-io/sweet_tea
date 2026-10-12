"""A base reached through a dotted path rather than imported by name."""

from tests.typed_candidate_cases import t01_base


class Triangle(t01_base.Shape):
    def area(self) -> int:
        return 3
