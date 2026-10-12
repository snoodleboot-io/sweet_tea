"""A base that is itself a case in this tree, so the chain is two hops long."""

from tests.typed_candidate_cases.t02_direct import Circle


class RoundedCircle(Circle):
    def area(self) -> int:
        return 4
