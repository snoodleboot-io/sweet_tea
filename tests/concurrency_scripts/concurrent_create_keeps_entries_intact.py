"""Many threads calling Factory.create on a lazily filled registry.

entries() copies the list, not the entries, so a caller holds the registry's own
Entry objects. Reading class_def used to write the public class_object field on them,
which flipped is_lazy and changed identity on a live entry -- so it survived
resolution's drop and slipped past the dedupe index, duplicating entries until a key
became ambiguous and create() raised (SWE-37).
"""

import sys
import tempfile
import threading
import warnings
from pathlib import Path

REPO = sys.argv[1]
sys.path.insert(0, REPO)

from sweet_tea.factory import Factory  # noqa: E402
from sweet_tea.registry import Registry  # noqa: E402
from sweet_tea.sweet_tea_error import SweetTeaError  # noqa: E402
from sweet_tea.sweet_tea_warning import SweetTeaWarning  # noqa: E402

warnings.simplefilter("ignore", SweetTeaWarning)

MODULES, ITERATIONS, THREADS = 24, 40, 24

tree = Path(tempfile.mkdtemp()) / "racepkg"
tree.mkdir()
(tree / "__init__.py").write_text("")
for index in range(MODULES):
    (tree / f"m{index}.py").write_text(
        f"class Alpha{index}:\n    pass\n\n\nclass Beta{index}:\n    pass\n"
    )
sys.path.insert(0, str(tree.parent))

EXPECTED = MODULES * 2
bad_iterations = 0
failures: list[str] = []

for _ in range(ITERATIONS):
    for attribute in (
        "registry",
        "seen",
        "lookup",
        "lookup_keys",
        "unresolved",
        "fills",
        "skipped",
        "strict_fills",
        "loaded_sources",
    ):
        getattr(Registry, f"_Registry__{attribute}").clear()
    for name in [n for n in list(sys.modules) if n.startswith("racepkg")]:
        del sys.modules[name]

    Registry.fill_registry(path=str(tree), module="racepkg", lazy=True)

    start = threading.Barrier(THREADS)

    def worker() -> None:
        start.wait(timeout=30)
        for index in range(MODULES):
            for prefix in ("alpha", "beta"):
                try:
                    Factory.create(f"{prefix}{index}")
                except SweetTeaError as error:
                    failures.append(str(error))

    threads = [threading.Thread(target=worker) for _ in range(THREADS)]
    for thread in threads:
        thread.daemon = True
        thread.start()
    for thread in threads:
        thread.join(60)

    keys = [entry.key for entry in Registry.entries()]
    if len(keys) != EXPECTED or len(keys) != len(set(keys)):
        bad_iterations += 1

if failures:
    print(f"CREATE FAILED {len(failures)}x: {failures[0][:90]}")
elif bad_iterations:
    print(f"REGISTRY CORRUPTED in {bad_iterations}/{ITERATIONS} iterations")
else:
    print("OK")
