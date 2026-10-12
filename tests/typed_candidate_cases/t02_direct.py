"""A base named plainly, the common case."""

from tests.typed_candidate_cases.t01_base import Shape


class Circle(Shape):
    def area(self) -> int:
        return 1
