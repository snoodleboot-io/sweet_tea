"""A module that cannot be imported on this platform, like click._winconsole."""

import sys

assert sys.platform == "definitely-not-this-platform"


class Unreachable:
    pass
