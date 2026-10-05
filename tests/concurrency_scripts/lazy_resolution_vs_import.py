"""Lazy resolution in one thread, an import of the same module in another.

__resolve_module imports while holding the registry lock, so it is rank-ordered
against the per-module import lock a concurrent importer already holds.
"""

import importlib
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
from sweet_tea.sweet_tea_warning import SweetTeaWarning  # noqa: E402

warnings.simplefilter("ignore", SweetTeaWarning)

tree = Path(tempfile.mkdtemp()) / "dlpkg"
tree.mkdir()
(tree / "__init__.py").write_text("")
(tree / "other.py").write_text("class OtherThing:\n    pass\n")
(tree / "consumer.py").write_text(textwrap.dedent(f"""
        import sys
        import time

        sys.path.insert(0, {REPO!r})
        from sweet_tea.factory import Factory


        class ConsumerThing:
            pass


        # Hold this module's import lock, then ask the registry for something.
        time.sleep(0.4)
        OTHER = Factory.create("otherthing")
        """))
sys.path.insert(0, str(tree.parent))

Registry.fill_registry(path=str(tree), module="dlpkg", lazy=True)

done = set()


def importer():
    importlib.import_module("dlpkg.consumer")
    done.add("import")


def lookup():
    time.sleep(0.15)
    Factory.create("consumerthing")
    done.add("lookup")


threads = [threading.Thread(target=importer), threading.Thread(target=lookup)]
for thread in threads:
    thread.daemon = True
    thread.start()
for thread in threads:
    thread.join(15)

print("OK" if done == {"import", "lookup"} else f"INCOMPLETE {sorted(done)}")
