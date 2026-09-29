import sys

if sys.version_info >= (3, 8):

    class Conditional:
        pass

else:

    class Conditional:
        pass


try:
    import json

    class TryBranch:
        pass

except ImportError:

    class TryBranch:
        pass
