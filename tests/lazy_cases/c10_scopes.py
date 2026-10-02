def _inner():
    class NeverSeen:
        pass

    return NeverSeen


class Outer:
    class Nested:
        pass
