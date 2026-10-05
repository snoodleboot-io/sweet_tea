"""SingletonFactory's lock and the registry's lock, acquired in both orders.

A singleton whose constructor locates a collaborator takes SF -> Registry. A module
body that creates a singleton, imported during resolution, takes Registry -> SF.
"""

import sys
import tempfile
import textwrap
import threading
import time
import warnings
from pathlib import Path

REPO = sys.argv[1]
sys.path.insert(0, REPO)

from sweet_tea.factory import Factory  # noqa: E402
from sweet_tea.registry import Registry  # noqa: E402
from sweet_tea.singleton_factory import SingletonFactory  # noqa: E402
from sweet_tea.sweet_tea_warning import SweetTeaWarning  # noqa: E402

warnings.simplefilter("ignore", SweetTeaWarning)

tree = Path(tempfile.mkdtemp()) / "invpkg"
tree.mkdir()
(tree / "__init__.py").write_text("")
(tree / "beta.py").write_text("class Beta:\n    pass\n")
(tree / "delta.py").write_text("class Delta:\n    pass\n")
(tree / "alpha.py").write_text(textwrap.dedent(f"""
        import sys
        import time

        sys.path.insert(0, {REPO!r})
        from sweet_tea.factory import Factory


        class Alpha:
            def __init__(self):
                # An ordinary service locating a collaborator.
                time.sleep(0.3)
                self.beta = Factory.create("beta")
        """))
(tree / "gamma.py").write_text(textwrap.dedent(f"""
        import sys
        import time

        sys.path.insert(0, {REPO!r})
        from sweet_tea.singleton_factory import SingletonFactory


        class Gamma:
            pass


        # An ordinary module-level service handle.
        time.sleep(0.3)
        SERVICE = SingletonFactory.create("delta")
        """))
sys.path.insert(0, str(tree.parent))

Registry.fill_registry(path=str(tree), module="invpkg", lazy=True)

done = set()


def singleton_side():
    SingletonFactory.create("alpha")
    done.add("singleton")


def factory_side():
    time.sleep(0.1)
    Factory.create("gamma")
    done.add("factory")


threads = [
    threading.Thread(target=singleton_side),
    threading.Thread(target=factory_side),
]
for thread in threads:
    thread.daemon = True
    thread.start()
for thread in threads:
    thread.join(15)

print("OK" if done == {"singleton", "factory"} else f"INCOMPLETE {sorted(done)}")
