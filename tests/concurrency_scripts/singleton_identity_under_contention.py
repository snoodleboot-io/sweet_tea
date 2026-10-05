"""Many threads, one key, four spellings: exactly one instance, built exactly once.

This is what the factory exists to guarantee, and it used to rest on holding the
factory's lock across construction. Construction is now admitted by a per-key lock
instead, so the guarantee needs proving rather than assuming.
"""

import sys
import tempfile
import textwrap
import threading
import warnings
from pathlib import Path

REPO = sys.argv[1]
sys.path.insert(0, REPO)

from sweet_tea.registry import Registry  # noqa: E402
from sweet_tea.singleton_factory import SingletonFactory  # noqa: E402
from sweet_tea.sweet_tea_warning import SweetTeaWarning  # noqa: E402

warnings.simplefilter("ignore", SweetTeaWarning)

tree = Path(tempfile.mkdtemp()) / "ctpkg"
tree.mkdir()
(tree / "__init__.py").write_text("")
(tree / "counted_service.py").write_text(textwrap.dedent("""
        import threading
        import time

        # Slow enough that every thread is inside create() before the first finishes.
        time.sleep(0.3)

        INVOCATIONS = []
        _GUARD = threading.Lock()


        class CountedService:
            def __init__(self):
                with _GUARD:
                    INVOCATIONS.append(1)
                time.sleep(0.05)
        """))
sys.path.insert(0, str(tree.parent))

Registry.fill_registry(path=str(tree), module="ctpkg", lazy=True)

SPELLINGS = ["CountedService", "counted_service", "countedservice", "COUNTEDSERVICE"]
start = threading.Barrier(32)
results: list[object] = []
errors: list[str] = []
guard = threading.Lock()


def worker(index: int) -> None:
    try:
        start.wait(timeout=10)
        instance = SingletonFactory.create(SPELLINGS[index % len(SPELLINGS)])
        with guard:
            results.append(instance)
    except Exception as error:  # noqa: BLE001
        with guard:
            errors.append(f"{type(error).__name__}: {error}")


threads = [threading.Thread(target=worker, args=(i,)) for i in range(32)]
for thread in threads:
    thread.daemon = True
    thread.start()
for thread in threads:
    thread.join(20)

import ctpkg.counted_service as module  # noqa: E402

distinct = len({id(instance) for instance in results})
invocations = len(module.INVOCATIONS)
slots = len(SingletonFactory.list_singletons())

if errors:
    print(f"ERRORS {errors[:3]}")
elif len(results) != 32:
    print(f"INCOMPLETE only {len(results)}/32 returned")
elif distinct != 1 or invocations != 1 or slots != 1:
    print(f"BROKEN distinct={distinct} invocations={invocations} slots={slots}")
else:
    print("OK")
