"""Registers as an import side effect, so the key is missing until a sweep."""

from sweet_tea.registry import Registry


class SideEffect:
    pass


Registry.register(key="registered_by_side_effect", class_def=SideEffect)
