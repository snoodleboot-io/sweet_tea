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
Tests for SWE-42: applying a declared configuration model to judge drift must not raise
out of create(), and must not run the consumer's validators more often than needed.
"""

import warnings
from typing import Any, ClassVar
from unittest import TestCase

from pydantic import BaseModel, field_validator

from sweet_tea.registry import Registry
from sweet_tea.singleton_factory import SingletonFactory
from sweet_tea.sweet_tea_error import SweetTeaError
from sweet_tea.sweet_tea_warning import SweetTeaWarning


class BrittleSettings(BaseModel):
    """A model whose validator raises on its own account rather than returning no.

    ``endpoint`` is untyped, so pydantic accepts anything and the validator is the only
    thing that looks at the value — which is how a validator comes to raise an
    AttributeError instead of a ValidationError.
    """

    endpoint: object = ""

    @field_validator("endpoint")
    @classmethod
    def strip_it(cls, value: Any) -> Any:
        """Strip the endpoint, assuming a string the way consumer code does."""
        return value.strip()


class BrittleService:
    """A class whose declared model raises on a value of the wrong type."""

    __configuration__ = BrittleSettings

    def __init__(self, endpoint: Any = "") -> None:
        self.endpoint = endpoint


class StrictSettings(BaseModel):
    """A model that says no the way pydantic does, by failing validation."""

    retries: int = 3


class StrictService:
    """A class whose declared model rejects what it cannot coerce."""

    __configuration__ = StrictSettings

    def __init__(self, retries: int = 3) -> None:
        self.retries = retries


class CountingSettings(BaseModel):
    """A model that records how often it is validated."""

    calls: ClassVar[int] = 0

    value: int = 0

    @field_validator("value")
    @classmethod
    def count(cls, value: int) -> int:
        """Count this validation, as an expensive validator's side effect would."""
        CountingSettings.calls += 1
        return value


class CountedService:
    """A class whose declared model is the one being counted."""

    __configuration__ = CountingSettings

    def __init__(self, value: int = 0) -> None:
        self.value = value


class TestSingletonConfigurationValidation(TestCase):
    """A warning path may decline to decide; it may not raise, and it may not repeat."""

    def setUp(self):
        Registry._Registry__registry.clear()
        Registry._Registry__seen.clear()
        Registry._Registry__lookup.clear()
        Registry._Registry__lookup_keys.clear()
        Registry._Registry__unresolved.clear()
        SingletonFactory.clear()
        Registry.register(key="BrittleService", class_def=BrittleService)
        Registry.register(key="StrictService", class_def=StrictService)
        Registry.register(key="CountedService", class_def=CountedService)
        CountingSettings.calls = 0

    def tearDown(self):
        SingletonFactory.clear()

    def create(self, key, **kwargs):
        """Call create, returning (instance, drift warnings)."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", SweetTeaWarning)
            instance = SingletonFactory.create(key=key, **kwargs)
        drift = [w for w in caught if "Ignoring the configuration" in str(w.message)]
        return instance, drift

    def test_a_validator_that_raises_does_not_raise_out_of_a_cache_hit(self):
        """A call that only needs the cached instance gets it, whatever the declared
        model does with the configuration it will never be built from."""
        first, _ = self.create("BrittleService", configuration={"endpoint": " A "})

        second, _ = self.create("BrittleService", configuration={"endpoint": 42})

        self.assertIs(second, first)
        self.assertEqual(second.endpoint, "A")

    def test_a_basis_that_cannot_be_computed_stays_silent(self):
        """A comparison that cannot be made is undecidable, not drift: the same ruling
        a value whose == is not boolean already gets."""
        self.create("BrittleService", configuration={"endpoint": " A "})

        _, drift = self.create("BrittleService", configuration={"endpoint": 42})

        self.assertEqual(drift, [])

    def test_an_undecidable_basis_does_not_warn_on_every_call(self):
        """Silence has to hold across repeated calls, which is why it beats a warning."""
        self.create("BrittleService", configuration={"endpoint": " A "})

        for _ in range(3):
            _, drift = self.create("BrittleService", configuration={"endpoint": 42})
            self.assertEqual(drift, [])

    def test_a_configuration_the_schema_rejects_still_warns(self):
        """A model that validates the cached configuration and refuses this one has
        decided they differ, which is drift and stays reportable."""
        first, _ = self.create("StrictService", configuration={"retries": 5})

        second, drift = self.create("StrictService", configuration={"retries": "many"})

        self.assertIs(second, first)
        self.assertEqual(len(drift), 1)

    def test_a_constructing_call_still_raises_what_the_validator_raised(self):
        """Nothing is being returned to the caller on a miss, so a declared model that
        cannot be applied is a create that must fail rather than fall silent."""
        with self.assertRaises(AttributeError):
            SingletonFactory.create(
                key="BrittleService", configuration={"endpoint": 42}
            )

        self.assertEqual(SingletonFactory.list_singletons(), [])

    def test_a_constructing_call_still_raises_on_a_rejected_configuration(self):
        """The declared model's considered no remains a SweetTeaError out of create."""
        with self.assertRaises(SweetTeaError):
            SingletonFactory.create(
                key="StrictService", configuration={"retries": "many"}
            )

        self.assertEqual(SingletonFactory.list_singletons(), [])

    def test_a_construction_validates_the_declared_model_once(self):
        """The basis is of what construction would use, so it reuses what construction
        validated rather than validating the consumer's model a second time."""
        instance, _ = self.create("CountedService", configuration={"value": 1})

        self.assertEqual(instance.value, 1)
        self.assertEqual(CountingSettings.calls, 1)

    def test_a_cache_hit_without_a_configuration_validates_nothing(self):
        """Fetching an existing singleton asks no question about drift, so it must not
        run the consumer's validators at all."""
        self.create("CountedService", configuration={"value": 1})
        CountingSettings.calls = 0

        for _ in range(3):
            self.create("CountedService")

        self.assertEqual(CountingSettings.calls, 0)

    def test_a_cache_hit_with_a_configuration_validates_once(self):
        """Judging that configuration needs the schema applied to it exactly once."""
        self.create("CountedService", configuration={"value": 1})
        CountingSettings.calls = 0

        self.create("CountedService", configuration={"value": 1})

        self.assertEqual(CountingSettings.calls, 1)

    def test_construction_still_builds_from_the_validated_model(self):
        """Construction is handed the already-applied configuration, so the schema's
        coercions and defaults must still be what reaches the constructor."""
        instance, _ = self.create("StrictService", configuration={"retries": "7"})

        self.assertEqual(instance.retries, 7)
        self.assertIsInstance(instance.retries, int)
