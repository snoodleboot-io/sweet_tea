"""
Tests for SWE-36 and SWE-39: construction that can never finish must be reported, and
clear() must not break the single-instance guarantee.

A re-entrant or circular singleton used to block forever on a per-key construction
lock, which is the one failure mode a container must not hand a consumer: no
traceback, no timeout, nothing to debug. These scenarios therefore run in
subprocesses with timeouts, the way tests/test_registry_concurrency.py runs its own
(SWE-22) — a regression must fail CI rather than hang it.
"""

import os
import subprocess
import sys
from unittest import TestCase

from sweet_tea.registry import Registry
from sweet_tea.singleton_factory import SingletonFactory

SCRIPTS = os.path.join(os.path.dirname(__file__), "concurrency_scripts")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Leaf:
    """A collaborator that depends on nothing."""


class Trunk:
    """Locates its collaborator in its constructor, which is ordinary injection."""

    def __init__(self) -> None:
        self.leaf = SingletonFactory.create(key="Leaf")


def run_scenario(name: str, timeout: int = 90) -> str:
    """
    Run one construction scenario and return its verdict line.

    Deliberately a copy of the helper in tests/test_registry_concurrency.py rather
    than an import of it: test modules that import one another break as soon as one
    is run alone, and the duplication is a dozen lines of subprocess plumbing.

    Args:
        name: Script name without the .py suffix.
        timeout: Seconds to allow. Generous: these scripts park threads deliberately
            to hold windows open, and CI machines are slow and shared.

    Returns:
        The last line the script printed.

    Raises:
        AssertionError: When the script does not finish, which is what the hang these
            tests exist to prevent looks like from out here.
    """
    try:
        completed = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, f"{name}.py"), REPO],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise AssertionError(
            f"{name} did not finish within {timeout}s, which means a construction "
            f"blocked forever. Run it directly to see where: python3 "
            f"tests/concurrency_scripts/{name}.py ."
        ) from None

    output = (completed.stdout or "").strip().splitlines()
    if not output:
        raise AssertionError(
            f"{name} printed nothing. stderr:\n{(completed.stderr or '').strip()}"
        )
    return output[-1]


class TestCircularConstructionIsReported(TestCase):
    """A construction that cannot finish must raise, naming the cycle."""

    def test_a_cycle_within_one_thread_is_named(self):
        """Self-referential and two-class cycles hung on a lock the thread held."""
        self.assertEqual(run_scenario("singleton_construction_cycles"), "OK")

    def test_a_cycle_entered_from_two_threads_is_named(self):
        """Opposite ends of one cycle inverted the per-key lock order."""
        self.assertEqual(run_scenario("singleton_cycle_across_threads"), "OK")


class TestClearDuringConstruction(TestCase):
    """clear() must not admit a second constructor for a key already being built."""

    def test_only_one_constructor_runs_per_key_across_a_clear(self):
        """Clearing the construction locks let a fresh lock admit a second thread."""
        verdict = run_scenario("singleton_clear_during_construction")

        self.assertTrue(verdict.startswith("OK"), verdict)


class TestDependencyInjectionStillWorks(TestCase):
    """A constructor that creates a different singleton is not a cycle."""

    def setUp(self):
        """Clear both the registry and the singleton cache."""
        Registry._Registry__registry.clear()
        Registry._Registry__lookup.clear()
        Registry._Registry__lookup_keys.clear()
        SingletonFactory.clear()

    def test_injected_collaborator_is_the_cached_singleton(self):
        """Resolving a collaborator during construction must share one instance."""
        Registry.register(key="Leaf", class_def=Leaf)
        Registry.register(key="Trunk", class_def=Trunk)

        trunk = SingletonFactory.create(key="Trunk")

        self.assertIs(trunk.leaf, SingletonFactory.create(key="Leaf"))
        self.assertEqual(sorted(SingletonFactory.list_singletons()), ["leaf", "trunk"])

    def test_a_cleared_key_is_constructible_again(self):
        """A construction lock kept across clear() must still admit the next caller."""
        Registry.register(key="Leaf", class_def=Leaf)
        Registry.register(key="Trunk", class_def=Trunk)

        first = SingletonFactory.create(key="Trunk")
        SingletonFactory.clear()
        second = SingletonFactory.create(key="Trunk")

        self.assertIsInstance(second, Trunk)
        self.assertIsNot(second, first)
