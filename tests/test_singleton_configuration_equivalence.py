# Modifications © 2025 snoodleboot, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Tests for SWE-29: drift is judged on the keyword arguments construction would use, not
on what the caller typed. Four of SWE-14's false positives fall silent and two of its
false negatives speak up, while the ten cases SWE-14 locked in stay as they were.
"""

import threading
import warnings
from typing import Any
from unittest import TestCase

from pydantic import BaseModel

from sweet_tea.registry import Registry
from sweet_tea.singleton_factory import SingletonFactory
from sweet_tea.sweet_tea_warning import SweetTeaWarning


class Settings(BaseModel):
    """A declared configuration model whose default a caller may also spell out."""

    retries: int = 3


class Service:
    """A class that declares the model its configuration is validated into."""

    __configuration__ = Settings

    def __init__(self, retries: int = 3) -> None:
        self.retries = retries


class Flexible:
    """A class that accepts whatever configuration a test sends it."""

    def __init__(self, **configuration: Any) -> None:
        self.configuration = configuration


class Collector:
    """A class that mutates the container it was handed, as constructors may."""

    def __init__(self, items: list[Any] | None = None) -> None:
        self.items = items
        if items is not None:
            items.append("built")


class TestSingletonConfigurationEquivalence(TestCase):
    """The drift warning fires when, and only when, construction would have differed."""

    def setUp(self):
        Registry._Registry__registry.clear()
        Registry._Registry__seen.clear()
        Registry._Registry__lookup.clear()
        Registry._Registry__lookup_keys.clear()
        Registry._Registry__unresolved.clear()
        SingletonFactory.clear()
        Registry.register(key="Service", class_def=Service)
        Registry.register(key="Flexible", class_def=Flexible)
        Registry.register(key="Collector", class_def=Collector)

    def tearDown(self):
        SingletonFactory.clear()

    def create(self, key, **kwargs):
        """Call create, returning (instance, drift warnings)."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", SweetTeaWarning)
            instance = SingletonFactory.create(key=key, **kwargs)
        drift = [w for w in caught if "Ignoring the configuration" in str(w.message)]
        return instance, drift

    def test_empty_dict_after_no_configuration_is_silent(self):
        """None and {} construct identically, so they are the same request."""
        self.create("Flexible")
        _, drift = self.create("Flexible", configuration={})

        self.assertEqual(drift, [])

    def test_empty_dict_is_a_fetch_rather_than_a_configuration(self):
        """configuration=options.get("cfg", {}) asks for the singleton, not a rebuild."""
        self.create("Flexible", configuration={"host": "primary"})
        _, drift = self.create("Flexible", configuration={})

        self.assertEqual(drift, [])

    def test_schema_default_spelled_out_is_silent(self):
        """A declared default and the same value typed by the caller build one instance."""
        self.create("Service")
        _, drift = self.create("Service", configuration={"retries": 3})

        self.assertEqual(drift, [])

    def test_empty_dict_then_declared_model_is_silent(self):
        """Two spellings of the same validated model are one configuration."""
        self.create("Service", configuration={})
        _, drift = self.create("Service", configuration=Settings())

        self.assertEqual(drift, [])

    def test_a_schema_decides_which_spellings_are_equivalent(self):
        """Under a declared model, both spellings are coerced before being compared."""
        self.create("Service", configuration={"retries": 1})
        _, drift = self.create("Service", configuration={"retries": True})

        self.assertEqual(drift, [])

    def test_differing_values_under_a_schema_still_warn(self):
        """Applying the schema must not flatten a genuine difference into agreement."""
        self.create("Service", configuration={"retries": 5})
        _, drift = self.create("Service", configuration={"retries": 7})

        self.assertEqual(len(drift), 1)

    def test_a_configuration_the_schema_rejects_warns_without_raising(self):
        """A configuration that will not validate cannot be the one that was used, and
        this caller gets no ValidationError either, so it is reported."""
        first, _ = self.create("Service", configuration={"retries": 5})
        second, drift = self.create("Service", configuration={"retries": "many"})

        self.assertIs(second, first)
        self.assertEqual(len(drift), 1)

    def test_constructor_mutation_does_not_blame_the_next_caller(self):
        """The basis is snapshotted before construction, so the constructor's own edit
        is not charged to whoever calls next."""
        shared = ["a"]
        self.create("Collector", configuration={"items": shared})
        self.assertEqual(shared, ["a", "built"])

        _, drift = self.create("Collector", configuration={"items": ["a"]})

        self.assertEqual(drift, [])

    def test_distinct_nan_values_are_the_same_request(self):
        """A caller passing NaN twice asked for the same thing both times."""
        self.create("Flexible", configuration={"x": float("nan")})
        _, drift = self.create("Flexible", configuration={"x": float("nan")})

        self.assertEqual(drift, [])

    def test_nested_mutation_warns(self):
        """The second caller asked for something different and did not get it."""
        nested = {"opts": {"mode": "fast"}}
        self.create("Flexible", configuration=nested)
        nested["opts"]["mode"] = "slow"

        _, drift = self.create("Flexible", configuration=nested)

        self.assertEqual(len(drift), 1)

    def test_top_level_mutation_still_warns(self):
        """The case the shallow copy already caught must survive the deep one."""
        configuration = {"host": "primary"}
        self.create("Flexible", configuration=configuration)
        configuration["host"] = "replica"

        _, drift = self.create("Flexible", configuration=configuration)

        self.assertEqual(len(drift), 1)

    def test_equal_nested_configurations_are_silent(self):
        """Comparison walks containers, so equal structures are still equal."""
        self.create(
            "Flexible", configuration={"opts": {"mode": "fast"}, "tags": [1, 2]}
        )
        _, drift = self.create(
            "Flexible", configuration={"opts": {"mode": "fast"}, "tags": [1, 2]}
        )

        self.assertEqual(drift, [])

    def test_true_is_not_one(self):
        """Absent a declared schema, the type reaching the constructor is the request."""
        self.create("Flexible", configuration={"flag": 1})
        _, drift = self.create("Flexible", configuration={"flag": True})

        self.assertEqual(len(drift), 1)

    def test_an_integer_is_not_a_float(self):
        """Same ruling for 1 against 1.0, at any depth."""
        self.create("Flexible", configuration={"sizes": [1]})
        _, drift = self.create("Flexible", configuration={"sizes": [1.0]})

        self.assertEqual(len(drift), 1)

    def test_a_value_that_cannot_be_copied_is_compared_as_it_is(self):
        """A lock will not deep-copy; keeping the reference keeps the case decidable."""
        lock = threading.Lock()
        self.create("Flexible", configuration={"lock": lock})

        _, same = self.create("Flexible", configuration={"lock": lock})
        _, different = self.create("Flexible", configuration={"lock": threading.Lock()})

        self.assertEqual(same, [])
        self.assertEqual(len(different), 1)

    def test_a_lazily_registered_singleton_still_reports_drift(self):
        """The comparison reads the class the lookup already resolved, so it needs no
        import of its own and still has a schema to apply."""
        Registry.register_lazy(
            key="LazyEntry", module="sweet_tea.entry", attribute="Entry"
        )
        self.create("LazyEntry", configuration={"key": "first"})

        _, drift = self.create("LazyEntry", configuration={"key": "second"})

        self.assertEqual(len(drift), 1)

    def test_an_uncopyable_value_does_not_cost_the_rest_of_the_basis(self):
        """One value kept by reference must not stop the others being snapshotted."""
        nested = {"lock": threading.Lock(), "opts": {"mode": "fast"}}
        self.create("Flexible", configuration=nested)
        nested["opts"]["mode"] = "slow"

        _, drift = self.create("Flexible", configuration=nested)

        self.assertEqual(len(drift), 1)
