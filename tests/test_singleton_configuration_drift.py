"""
Tests for SWE-14: a cached singleton is never rebuilt, so a configuration passed to a
later call is discarded. The behaviour stays; the silence does not.
"""

import warnings
from unittest import TestCase

from pydantic import BaseModel

from sweet_tea.registry import Registry
from sweet_tea.singleton_factory import SingletonFactory
from sweet_tea.sweet_tea_warning import SweetTeaWarning


class Settings(BaseModel):
    """Configuration model matching Connection's constructor."""

    host: str = "localhost"


class Connection:
    """Stand-in for a resource that must exist only once."""

    def __init__(self, host: str = "localhost") -> None:
        self.host = host


class Uncomparable:
    """A value whose equality is not boolean, like a numpy array."""

    def __eq__(self, other):  # noqa: D105
        raise ValueError("truth value is ambiguous")

    __hash__ = None


class TestSingletonConfigurationDrift(TestCase):
    """A configuration that arrived too late to matter is reported."""

    def setUp(self):
        Registry._Registry__registry.clear()
        Registry._Registry__seen.clear()
        Registry._Registry__lookup.clear()
        Registry._Registry__lookup_keys.clear()
        SingletonFactory.clear()
        Registry.register(key="Connection", class_def=Connection)

    def tearDown(self):
        SingletonFactory.clear()

    def create(self, **kwargs):
        """Call create, returning (instance, drift warnings)."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", SweetTeaWarning)
            instance = SingletonFactory.create(key="Connection", **kwargs)
        drift = [w for w in caught if "Ignoring the configuration" in str(w.message)]
        return instance, drift

    def test_differing_configuration_warns(self):
        """The case that was silent: a second, different configuration."""
        first, _ = self.create(configuration={"host": "primary"})
        second, drift = self.create(configuration={"host": "replica"})

        self.assertIs(second, first)
        self.assertEqual(second.host, "primary")
        self.assertEqual(len(drift), 1)
        self.assertIn("Connection".lower(), str(drift[0].message))

    def test_identical_configuration_is_silent(self):
        """Asking for what is already there is not a mistake."""
        self.create(configuration={"host": "primary"})
        _, drift = self.create(configuration={"host": "primary"})

        self.assertEqual(drift, [])

    def test_omitted_configuration_is_silent(self):
        """Fetching an existing singleton with no configuration is the normal idiom."""
        self.create(configuration={"host": "primary"})
        _, drift = self.create()

        self.assertEqual(drift, [])

    def test_first_call_never_warns(self):
        """There is nothing to drift from yet."""
        _, drift = self.create(configuration={"host": "primary"})

        self.assertEqual(drift, [])

    def test_model_matching_the_first_dict_is_silent(self):
        """A model and an equivalent dict build the same instance, so they agree."""
        self.create(configuration={"host": "primary"})
        _, drift = self.create(configuration=Settings(host="primary"))

        self.assertEqual(drift, [])

    def test_differing_model_warns(self):
        """Comparison happens on the fields, whatever carried them."""
        self.create(configuration=Settings(host="primary"))
        _, drift = self.create(configuration=Settings(host="replica"))

        self.assertEqual(len(drift), 1)

    def test_uncomparable_values_stay_silent(self):
        """Undecidable drift must not warn on every call, nor raise."""
        self.create(configuration={"host": Uncomparable()})
        _, drift = self.create(configuration={"host": Uncomparable()})

        self.assertEqual(drift, [])

    def test_pop_discards_the_recorded_configuration(self):
        """After removal there is nothing for the next call to disagree with."""
        self.create(configuration={"host": "primary"})
        SingletonFactory.pop("Connection")

        instance, drift = self.create(configuration={"host": "replica"})

        self.assertEqual(instance.host, "replica")
        self.assertEqual(drift, [])

    def test_clear_discards_the_recorded_configuration(self):
        """Same for a wholesale reset."""
        self.create(configuration={"host": "primary"})
        SingletonFactory.clear()

        instance, drift = self.create(configuration={"host": "replica"})

        self.assertEqual(instance.host, "replica")
        self.assertEqual(drift, [])

    def test_warning_points_at_the_caller(self):
        """The useful line is the create() whose configuration was dropped."""
        self.create(configuration={"host": "primary"})

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", SweetTeaWarning)
            SingletonFactory.create(key="Connection", configuration={"host": "replica"})

        self.assertEqual(len(caught), 1)
        self.assertTrue(
            caught[0].filename.endswith("test_singleton_configuration_drift.py"),
            caught[0].filename,
        )
