"""
Tests for SWE-22: the registry's lock guards its data, not module imports.

Each scenario runs in a subprocess with a timeout. A deadlock inside pytest would
hang the suite — and a hung CI job is far less useful than a failed one — so the
scenarios live as standalone scripts in tests/concurrency_scripts/ and each prints a
single verdict line this module asserts on.
"""

import os
import subprocess
import sys
from unittest import TestCase

SCRIPTS = os.path.join(os.path.dirname(__file__), "concurrency_scripts")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_scenario(name: str, timeout: int = 90) -> str:
    """
    Run one concurrency scenario and return its verdict line.

    Args:
        name: Script name without the .py suffix.
        timeout: Seconds to allow. Generous: these scripts sleep deliberately to
            widen the windows they probe, and CI machines are slow and shared.

    Returns:
        The last line the script printed.

    Raises:
        AssertionError: When the script does not finish, which is what a deadlock
            looks like from out here.
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
            f"{name} did not finish within {timeout}s, which means it deadlocked. "
            f"Run it directly to see both stacks: python3 "
            f"tests/concurrency_scripts/{name}.py ."
        ) from None

    output = (completed.stdout or "").strip().splitlines()
    if not output:
        raise AssertionError(
            f"{name} printed nothing. stderr:\n{(completed.stderr or '').strip()}"
        )
    return output[-1]


class TestNoDeadlockAcrossImports(TestCase):
    """Importing a module must not be able to deadlock against the registry."""

    def test_eager_fill_against_a_concurrent_import(self):
        """fill_registry held its lock across the whole walk, imports included."""
        self.assertEqual(run_scenario("eager_fill_vs_import"), "OK")

    def test_lazy_resolution_against_a_concurrent_import(self):
        """Resolution imports; it used to do so holding the registry's lock."""
        self.assertEqual(run_scenario("lazy_resolution_vs_import"), "OK")

    def test_singleton_and_registry_locks_do_not_invert(self):
        """A singleton locating a collaborator, against a module creating one."""
        self.assertEqual(run_scenario("singleton_lock_inversion"), "OK")


class TestGuaranteesUnderContention(TestCase):
    """What the lock was protecting must still hold now that it is narrower."""

    def test_one_instance_and_one_construction_per_key(self):
        """The singleton guarantee no longer rests on a lock held across __init__."""
        self.assertEqual(run_scenario("singleton_identity_under_contention"), "OK")

    def test_unrelated_imports_overlap(self):
        """Imports are I/O-bound and must not queue behind one another."""
        verdict = run_scenario("imports_overlap")

        self.assertTrue(verdict.startswith("OK"), verdict)
