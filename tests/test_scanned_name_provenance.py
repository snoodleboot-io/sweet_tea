"""
Tests for SWE-20: a scanned name is a guess, an explicit registration is a request.

Carry-forward keeps a lazy entry discovery will not reproduce, which is right for an
alias a consumer registered deliberately. Applied to names the *scanner* guessed at, it
registered classes from other distributions under this library's name.
"""

import os
import sys
import warnings
from unittest import TestCase

from sweet_tea.factory import Factory
from sweet_tea.registry import Registry
from sweet_tea.sweet_tea_warning import SweetTeaWarning

CASES_PATH = os.path.join(os.path.dirname(__file__), "provenance_cases")
CASES_MODULE = "tests.provenance_cases"


def reset_registry() -> None:
    """Clear every piece of registry state."""
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


def forget_cases() -> None:
    """Drop the fixture modules so each fill starts from the same place."""
    for name in [n for n in sys.modules if n.startswith(CASES_MODULE + ".")]:
        del sys.modules[name]


def fill(**kwargs) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SweetTeaWarning)
        Registry.fill_registry(path=CASES_PATH, module=CASES_MODULE, **kwargs)


def keys() -> set[str]:
    return {entry.key for entry in Registry.entries()}


class TestScannedNamesFollowDiscovery(TestCase):
    """A guess the scanner made is overruled by what the module turned out to hold."""

    def setUp(self):
        reset_registry()
        forget_cases()

    def tearDown(self):
        reset_registry()

    def resolved_lazy_keys(self) -> set[str]:
        fill(lazy=True)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.resolve_all()
        return keys()

    def test_lazy_matches_eager_exactly(self):
        """The parity SWE-10 rests on, over four shapes that used to break it."""
        fill()
        eager = keys()

        reset_registry()
        forget_cases()

        self.assertEqual(self.resolved_lazy_keys(), eager)

    def test_a_try_except_import_fallback_registers_nothing(self):
        """The commonest optional-dependency idiom registered a foreign class."""
        self.assertNotIn("encoder", self.resolved_lazy_keys())

    def test_new_class_registers_nothing(self):
        """types.new_class always claims `types`, so every such binding was lazy-only."""
        self.assertNotIn("made", self.resolved_lazy_keys())

    def test_a_foreign_declared_module_registers_nothing(self):
        """create_model(..., __module__=...) was the case this ticket started from."""
        self.assertNotIn("thing", self.resolved_lazy_keys())

    def test_an_ordinary_class_is_unaffected(self):
        """The rule must only drop what discovery would have refused."""
        self.assertIn("local", self.resolved_lazy_keys())


class TestExplicitEntriesAreStillRequests(TestCase):
    """SWE-17's guarantee: an alias a consumer asked for survives resolution."""

    def setUp(self):
        reset_registry()

    def tearDown(self):
        reset_registry()

    def register_alias(self, key: str, module: str) -> None:
        Registry.register_lazy(
            key=key, module=module, attribute="Plain", library="mylib", label="alias"
        )

    def test_an_alias_survives(self):
        """Not provisional, so discovery does not overrule it."""
        self.register_alias("my_alias", "tests.lazy_cases.c01_plain")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            instance = Factory.create("my_alias", library="mylib")

        self.assertEqual(instance.__class__.__name__, "Plain")

    def test_an_alias_to_a_re_export_survives(self):
        """The case the module filter would wrongly refuse: a deliberate re-export."""
        self.register_alias("reexport_alias", "tests.lazy_cases.c11_reexport")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            instance = Factory.create("reexport_alias", library="mylib")

        self.assertEqual(instance.__class__.__name__, "Plain")

    def test_register_lazy_defaults_to_a_request(self):
        """Only this module's scan marks entries provisional."""
        self.register_alias("plain_alias", "tests.lazy_cases.c01_plain")

        entry = next(e for e in Registry.entries() if e.key == "plain_alias")
        self.assertFalse(entry.provisional)
