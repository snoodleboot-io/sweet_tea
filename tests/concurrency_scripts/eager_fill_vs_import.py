"""Eager fill in one thread, an import of the same module in another.

The module body reads the registry, which is the cheapest call in the API. Thread A
takes the module's import lock and then wants the registry lock; thread B holds the
registry lock for the whole walk and then wants the module's import lock.
"""

import importlib
import sys
import tempfile
import textwrap
import threading
from pathlib import Path

REPO = sys.argv[1]
sys.path.insert(0, REPO)

from sweet_tea.registry import Registry  # noqa: E402

tree = Path(tempfile.mkdtemp()) / "epkg"
tree.mkdir()
(tree / "__init__.py").write_text("")
(tree / "target.py").write_text(textwrap.dedent(f"""
        import sys
        import time

        sys.path.insert(0, {REPO!r})
        from sweet_tea.registry import Registry


        class Target:
            pass


        # Hold this module's import lock while the filler takes the registry lock.
        time.sleep(0.4)
        KNOWN = Registry.entries()
        """))
sys.path.insert(0, str(tree.parent))

done = set()


def importer():
    importlib.import_module("epkg.target")
    done.add("import")


def filler():
    # Let the importer win the module lock first; that ordering is the cycle.
    import time

    time.sleep(0.15)
    Registry.fill_registry(path=str(tree), module="epkg")
    done.add("fill")


threads = [threading.Thread(target=importer), threading.Thread(target=filler)]
for thread in threads:
    thread.daemon = True
    thread.start()
for thread in threads:
    thread.join(15)

print("OK" if done == {"import", "fill"} else f"INCOMPLETE {sorted(done)}")
