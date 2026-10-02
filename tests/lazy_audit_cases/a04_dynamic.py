"""Builds classes at runtime, leaving nothing in the source to scan."""

import sys

for _name in ("Generated",):
    globals()[_name] = type(_name, (), {})

setattr(sys.modules[__name__], "Injected", type("Injected", (), {}))
