"""A class built by type(), which spells its bases in a tuple the scanner can read."""

from tests.typed_candidate_cases.t01_base import Shape

Made = type("Made", (Shape,), {"area": lambda self: 5})
