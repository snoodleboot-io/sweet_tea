"""The component the tests ask for."""

from tests.singleton_type_cases import s00_marker_real  # noqa: F401
from tests.singleton_type_cases.s01_base import Component


class RealComponent(Component):
    pass
