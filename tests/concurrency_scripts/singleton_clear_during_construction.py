"""SWE-39: clear() must not admit a second thread into a construction already running.

clear() used to empty the per-key construction locks. A thread holding one kept it
alive through its own reference, but the next caller for that key found the mapping
empty, created a *fresh* lock for the same key, took it unopposed and ran the
constructor again — concurrently with the first. Two instances of a singleton, out of
the reset API.

The constructor counts how many of itself are running at once, so the verdict measures
the guarantee rather than inferring it from identity: a singleton may legitimately be
constructed again *after* a clear, but never twice at the same time.

Two phases. The first pins the race open with events — one thread parked inside the
constructor, a clear() while it is parked, a second caller arriving afterwards — so the
regression is caught every run rather than one run in thirty. The second reproduces the
reported measurement, eight callers and a clear racing freely, as a check that nothing
else about the window matters.

Run as a subprocess: the parked constructor and the waiting caller both have timeouts,
but a regression in the construction lock itself is the kind of fault that hangs.
"""

import sys
import threading
import time
import warnings

REPO = sys.argv[1]
sys.path.insert(0, REPO)

from sweet_tea.registry import Registry  # noqa: E402
from sweet_tea.singleton_factory import SingletonFactory  # noqa: E402
from sweet_tea.sweet_tea_warning import SweetTeaWarning  # noqa: E402

warnings.simplefilter("ignore", SweetTeaWarning)

PINNED_ITERATIONS = 20
RACING_ITERATIONS = 300
CREATORS = 8

counter_guard = threading.Lock()
running = 0
peak = 0
constructions = 0

# Rebound per pinned iteration. The constructor announces itself through the first and
# stays inside until the second is set, which is what holds the window open.
entered = threading.Event()
release = threading.Event()
pin = False


class Counted:
    """Records how many constructions of this one key overlap in time."""

    def __init__(self):
        global running, peak, constructions
        with counter_guard:
            running += 1
            constructions += 1
            peak = max(peak, running)
        if pin:
            entered.set()
            release.wait(timeout=10)
        else:
            # Wide enough for a second admitted constructor to overlap this one
            # visibly; the duration the regression was measured at.
            time.sleep(0.003)
        with counter_guard:
            running -= 1


Registry.register(key="Counted", class_def=Counted)

errors: list[str] = []


def create_once() -> None:
    """Ask for the singleton once, recording any refusal as a failure."""
    try:
        SingletonFactory.create("counted")
    except Exception as error:  # noqa: BLE001
        with counter_guard:
            errors.append(f"{type(error).__name__}: {error}")


def run_pinned_iteration() -> None:
    """Hold one construction open, clear the factory under it, then call again."""
    global entered, release
    entered = threading.Event()
    release = threading.Event()
    SingletonFactory.clear()

    first = threading.Thread(target=create_once, name="parked-creator")
    first.daemon = True
    first.start()
    if not entered.wait(timeout=10):
        errors.append("the first constructor never started")
        return

    # Exactly the window: a construction lock is held, no instance is cached yet.
    SingletonFactory.clear()

    second = threading.Thread(target=create_once, name="late-creator")
    second.daemon = True
    second.start()
    # Long enough that a second constructor admitted by a fresh lock would be counted
    # before the first one leaves.
    time.sleep(0.05)

    with counter_guard:
        overlapping = running
    if overlapping != 1:
        errors.append(f"{overlapping} constructors were running at once")

    release.set()
    first.join(10)
    second.join(10)
    if first.is_alive() or second.is_alive():
        errors.append("a creator did not finish within 10s")


def run_racing_iteration() -> None:
    """Eight callers and a clear(), released together and left to race."""
    SingletonFactory.clear()
    start = threading.Barrier(CREATORS + 1)

    def creator() -> None:
        start.wait(timeout=10)
        create_once()

    def clearer() -> None:
        start.wait(timeout=10)
        # Mid-construction rather than before it: the window opens once a caller holds
        # a construction lock and has not yet cached anything.
        time.sleep(0.001)
        SingletonFactory.clear()

    threads = [threading.Thread(target=creator) for _ in range(CREATORS)]
    threads.append(threading.Thread(target=clearer))
    for thread in threads:
        thread.daemon = True
        thread.start()
    for thread in threads:
        thread.join(30)
    if any(thread.is_alive() for thread in threads):
        errors.append("a thread did not finish within 30s")


pin = True
for _ in range(PINNED_ITERATIONS):
    if errors:
        break
    run_pinned_iteration()

pin = False
for _ in range(RACING_ITERATIONS):
    if errors:
        break
    run_racing_iteration()

if errors:
    print(f"ERRORS {errors[:3]}")
elif peak != 1:
    print(f"BROKEN {peak} constructors ran at once, constructions={constructions}")
else:
    print(
        f"OK peak=1 pinned={PINNED_ITERATIONS} racing={RACING_ITERATIONS} "
        f"constructions={constructions}"
    )
