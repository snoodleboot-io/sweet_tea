"""A base renamed on import, so the only spelling in source is not the class name."""

from tests.typed_candidate_cases.t01_base import Shape as Form


class Square(Form):
    def area(self) -> int:
        return 2
