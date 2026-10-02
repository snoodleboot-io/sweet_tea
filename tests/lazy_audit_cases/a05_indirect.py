"""The registry read is one hop away, in a function the module body calls."""

from sweet_tea.factory import Factory


class Indirect:
    pass


def _warm_up():
    try:
        return Factory.create("indirect")
    except Exception:
        return None


WARMED = _warm_up()
