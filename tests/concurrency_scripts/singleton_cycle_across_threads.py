"""SWE-36 entered from both ends at once: one cycle, two threads, inverted locks.

Thread A creates alpha, whose constructor needs beta; thread B creates beta, whose
constructor needs alpha. Each holds the construction lock the other is about to ask
for, so neither thread's own construction stack can see the cycle — the only thing
that can is the wait-for graph across threads.

The ordering is forced with events rather than sleeps: each constructor announces that
it holds its own lock and waits for the other to announce the same before reaching
across. That makes the lock-order inversion certain instead of likely, so the scenario
tests the cross-thread detection every run rather than usually.

Run as a subprocess with a timeout: before the fix this deadlocked outright.
"""

import sys
import threading
import warnings

REPO = sys.argv[1]
sys.path.insert(0, REPO)

from sweet_tea.registry import Registry  # noqa: E402
from sweet_tea.singleton_factory import SingletonFactory  # noqa: E402
from sweet_tea.sweet_tea_warning import SweetTeaWarning  # noqa: E402

warnings.simplefilter("ignore", SweetTeaWarning)

alpha_locked = threading.Event()
beta_locked = threading.Event()


class Alpha:
    """Holds alpha's construction lock, then asks for beta's."""

    def __init__(self):
        alpha_locked.set()
        beta_locked.wait(timeout=10)
        self.beta = SingletonFactory.create("beta")


class Beta:
    """Holds beta's construction lock, then asks for alpha's."""

    def __init__(self):
        beta_locked.set()
        alpha_locked.wait(timeout=10)
        self.alpha = SingletonFactory.create("alpha")


Registry.register(key="Alpha", class_def=Alpha)
Registry.register(key="Beta", class_def=Beta)

refusals: list[str] = []
guard = threading.Lock()


def enter(key: str) -> None:
    """
    Create one end of the cycle and record how it was refused.

    Args:
        key: The end of the cycle this thread enters from.
    """
    try:
        SingletonFactory.create(key)
        verdict = f"{key}: CREATED"
    except Exception as error:  # noqa: BLE001
        verdict = f"{key}: {type(error).__name__}: {error}"
    with guard:
        refusals.append(verdict)


threads = [
    threading.Thread(target=enter, args=("alpha",), name="alpha-side"),
    threading.Thread(target=enter, args=("beta",), name="beta-side"),
]
for thread in threads:
    thread.daemon = True
    thread.start()
for thread in threads:
    thread.join(20)

problems = []

if len(refusals) != 2:
    problems.append(f"only {len(refusals)}/2 threads finished: {refusals}")
else:
    if not all("SweetTeaError" in refusal for refusal in refusals):
        problems.append(f"a thread was not refused with SweetTeaError: {refusals}")
    # The thread that registers its wait second sees the graph closed and reports the
    # deadlock. Its unwinding frees the other, which then meets the same cycle on its
    # own stack and reports that — so exactly one of each, whichever thread got there
    # first.
    deadlocks = [r for r in refusals if "Deadlocked singleton construction" in r]
    cycles = [r for r in refusals if "Circular singleton construction" in r]
    if len(deadlocks) != 1:
        problems.append(f"expected one cross-thread deadlock report: {refusals}")
    if len(cycles) != 1:
        problems.append(f"expected one same-thread cycle report: {refusals}")

cached = SingletonFactory.list_singletons()
if cached:
    problems.append(f"a refused construction left instances cached: {cached}")

print("OK" if not problems else f"BAD {problems}")
