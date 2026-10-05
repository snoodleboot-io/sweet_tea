"""SWE-36: a constructor that asks for a key already under construction, one thread.

Four shapes, three of which blocked forever on the per-key construction lock before
the fix: a self-referential constructor, a two-class cycle, the same cycle entered
from its other end, and — the one that must keep working — a constructor that creates
a *different* singleton, which is ordinary dependency injection and not a cycle at all.

Run as a subprocess with a timeout, because a regression here is a hang: a hung CI job
says far less than a failed one.
"""

import sys
import warnings

REPO = sys.argv[1]
sys.path.insert(0, REPO)

from sweet_tea.registry import Registry  # noqa: E402
from sweet_tea.singleton_factory import SingletonFactory  # noqa: E402
from sweet_tea.sweet_tea_error import SweetTeaError  # noqa: E402
from sweet_tea.sweet_tea_warning import SweetTeaWarning  # noqa: E402

warnings.simplefilter("ignore", SweetTeaWarning)


class SelfSeeking:
    """Asks the factory for the very instance it is being constructed as."""

    def __init__(self):
        self.self_reference = SingletonFactory.create("selfseeking")


class Alpha:
    """One half of an ordinary circular dependency between two services."""

    def __init__(self):
        self.beta = SingletonFactory.create("beta")


class Beta:
    """The other half: constructing either one needs the other to exist first."""

    def __init__(self):
        self.alpha = SingletonFactory.create("alpha")


class Plain:
    """A collaborator that depends on nothing."""


class Composed:
    """Locates a collaborator in its constructor, which is not a cycle."""

    def __init__(self):
        self.plain = SingletonFactory.create("plain")


for name, class_def in (
    ("SelfSeeking", SelfSeeking),
    ("Alpha", Alpha),
    ("Beta", Beta),
    ("Plain", Plain),
    ("Composed", Composed),
):
    Registry.register(key=name, class_def=class_def)


def refusal(key: str) -> Exception | None:
    """
    Create a singleton and report how it refused.

    Args:
        key: The key to create.

    Returns:
        The exception the call raised, or None when it returned an instance.
    """
    try:
        SingletonFactory.create(key)
    except Exception as error:  # noqa: BLE001
        return error
    return None


problems = []


def expect_cycle(key: str, cycle: str) -> None:
    """
    Require that creating a key is refused as a cycle, naming the path round it.

    Args:
        key: The key to create.
        cycle: The path the message must name, e.g. "alpha -> beta -> alpha".
    """
    error = refusal(key)
    if not isinstance(error, SweetTeaError):
        problems.append(f"{key} was not refused with SweetTeaError: {error!r}")
    elif cycle not in str(error):
        problems.append(f"{key} was refused without naming {cycle!r}: {error}")


# A constructor reaching back for its own key: single thread, hung before the fix.
expect_cycle("selfseeking", "selfseeking -> selfseeking")

# A two-class cycle, from either end. Both ends must name the path they went round.
expect_cycle("alpha", "alpha -> beta -> alpha")
expect_cycle("beta", "beta -> alpha -> beta")

# The cycle must not have poisoned the key: a second attempt is refused the same way
# rather than reporting a construction that is no longer in progress, or hanging on a
# construction lock a raising constructor failed to release.
expect_cycle("alpha", "alpha -> beta -> alpha")

# Nothing half-constructed may be cached.
cached = SingletonFactory.list_singletons()
if cached:
    problems.append(f"refused constructions left instances cached: {cached}")

# Dependency injection, which the cycle check must leave alone.
composed = SingletonFactory.create("composed")
if composed.plain is not SingletonFactory.create("plain"):
    problems.append("a constructor's collaborator was not the cached singleton")
if sorted(SingletonFactory.list_singletons()) != ["composed", "plain"]:
    problems.append(
        f"unexpected cache after injection: {SingletonFactory.list_singletons()}"
    )

print("OK" if not problems else f"BAD {problems}")
