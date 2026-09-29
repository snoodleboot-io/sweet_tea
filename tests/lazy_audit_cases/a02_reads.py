"""Reads the registry while being imported. Harmless to import, fatal under lazy."""

from sweet_tea.registry import Registry

KNOWN_AT_IMPORT = [entry.key for entry in Registry.entries()]


class ReadsRegistry:
    pass
