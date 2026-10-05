try:
    from tests.provenance_foreign import Encoder
except ImportError:

    class Encoder:
        pass
