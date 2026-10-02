for _name in ("LoopA", "LoopB"):
    globals()[_name] = type(_name, (), {})

import sys

setattr(sys.modules[__name__], "SetAttrMade", type("SetAttrMade", (), {}))
