"""A second component, so "only what was asked for" is observable."""

from tests.singleton_type_cases import s00_marker_other  # noqa: F401
from tests.singleton_type_cases.s01_base import Component


class OtherComponent(Component):
    pass
