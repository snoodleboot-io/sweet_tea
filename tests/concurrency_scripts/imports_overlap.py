"""Four slow imports in four threads should overlap, not queue behind one lock.

Each module sleeps at import. Holding the registry's lock across imports serialised
them, so four 0.5s imports cost 2s and an unrelated entries() call waited behind
them (SWE-22).
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
from sweet_tea.sweet_tea_warning import SweetTeaWarning  # noqa: E402

warnings.simplefilter("ignore", SweetTeaWarning)

SLEEP = 0.5
COUNT = 4

tree = Path(tempfile.mkdtemp()) / "ovpkg"
tree.mkdir()
(tree / "__init__.py").write_text("")
for index in range(COUNT):
    (tree / f"svc{index}.py").write_text(textwrap.dedent(f"""
            import time

            time.sleep({SLEEP})


            class Svc{index}:
                pass
            """))
sys.path.insert(0, str(tree.parent))

Registry.fill_registry(path=str(tree), module="ovpkg", lazy=True)

blocked_for = []


def create(index: int) -> None:
    Factory.create(f"svc{index}")


def cheap_read() -> None:
    time.sleep(0.05)
    started = time.perf_counter()
    Registry.entries()
    blocked_for.append(time.perf_counter() - started)


threads = [threading.Thread(target=create, args=(i,)) for i in range(COUNT)]
threads.append(threading.Thread(target=cheap_read))
begin = time.perf_counter()
for thread in threads:
    thread.daemon = True
    thread.start()
for thread in threads:
    thread.join(30)
elapsed = time.perf_counter() - begin

serial = SLEEP * COUNT
# Generous: overlapping should land near SLEEP, serialising near 2s. Anything under
# half the serial cost proves the imports are not queueing.
verdict = "OK" if elapsed < serial * 0.5 else "SERIALISED"
print(
    f"{verdict} elapsed={elapsed:.2f}s serial_would_be={serial:.2f}s "
    f"cheap_read_blocked={max(blocked_for or [0]):.3f}s"
)
