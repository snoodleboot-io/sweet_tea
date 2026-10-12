"""A subscripted base, whose name is not the whole expression."""

from tests.typed_candidate_cases.t01_base import Container


class BoxedInt(Container[int]):
    pass
