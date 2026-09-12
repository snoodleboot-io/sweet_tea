"""
Tests for SWE-7: factories accept a pydantic BaseModel as configuration and spread its
fields into the constructor exactly as they would a dict.
"""

from unittest import TestCase

from pydantic import BaseModel, ConfigDict

from sweet_tea.abstract_factory import AbstractFactory
from sweet_tea.factory import Factory
from sweet_tea.registry import Registry
from sweet_tea.singleton_factory import SingletonFactory


class PoolSettings(BaseModel):
    """Nested model, used to prove nested values are not serialized to dicts."""

    size: int = 5


class ConnectionSettings(BaseModel):
    """Flat configuration model matching Connection's constructor."""

    host: str
    port: int = 5432


class NestedConnectionSettings(BaseModel):
    """Configuration model carrying a nested model."""

    host: str
    pool: PoolSettings = PoolSettings()


class OpenConnectionSettings(BaseModel):
    """Configuration model that accepts undeclared fields."""

    model_config = ConfigDict(extra="allow")

    host: str


class Connection:
    """Base class for the abstract factory, with keyword-only construction."""

    def __init__(self, host: str = "localhost", port: int = 1) -> None:
        self.host = host
        self.port = port


class PooledConnection(Connection):
    """Receives a nested value that must keep its model type."""

    def __init__(self, host: str = "localhost", pool: object = None) -> None:
        super().__init__(host=host)
        self.pool = pool


class OpenConnection(Connection):
    """Accepts arbitrary extra keyword arguments."""

    def __init__(self, host: str = "localhost", **extras: object) -> None:
        super().__init__(host=host)
        self.extras = extras


class TestPydanticConfiguration(TestCase):
    """A BaseModel configuration must behave like the equivalent dict."""

    def setUp(self):
        """Clear both the registry and the singleton cache."""
        Registry._Registry__registry.clear()
        Registry._Registry__lookup.clear()
        Registry._Registry__lookup_keys.clear()
        SingletonFactory.clear()
        Registry.register(key="Connection", class_def=Connection)
        Registry.register(key="PooledConnection", class_def=PooledConnection)
        Registry.register(key="OpenConnection", class_def=OpenConnection)

    def test_factory_spreads_model_fields(self):
        """Model fields must arrive as constructor keyword arguments."""
        instance = Factory.create(
            key="Connection",
            configuration=ConnectionSettings(host="db", port=6543),
        )

        self.assertEqual((instance.host, instance.port), ("db", 6543))

    def test_model_matches_equivalent_dict(self):
        """A model and the dict of its fields must build identical instances."""
        from_model = Factory.create(
            key="Connection", configuration=ConnectionSettings(host="db", port=6543)
        )
        from_dict = Factory.create(
            key="Connection", configuration={"host": "db", "port": 6543}
        )

        self.assertEqual(vars(from_model), vars(from_dict))

    def test_model_defaults_override_class_defaults(self):
        """Every model field is sent, so a model default beats the class default."""
        instance = Factory.create(
            key="Connection", configuration=ConnectionSettings(host="db")
        )

        self.assertEqual(instance.port, 5432)

    def test_nested_model_is_not_serialized(self):
        """Nested models must reach the class as models, not as plain dicts."""
        pool = PoolSettings(size=20)

        instance = Factory.create(
            key="PooledConnection",
            configuration=NestedConnectionSettings(host="db", pool=pool),
        )

        self.assertIsInstance(instance.pool, PoolSettings)
        self.assertEqual(instance.pool.size, 20)

    def test_extra_fields_are_passed_through(self):
        """Fields accepted via extra="allow" must be spread along with declared ones."""
        instance = Factory.create(
            key="OpenConnection",
            configuration=OpenConnectionSettings(host="db", replica="db-2"),
        )

        self.assertEqual(instance.host, "db")
        self.assertEqual(instance.extras, {"replica": "db-2"})

    def test_none_and_dict_configurations_unchanged(self):
        """Existing dict and omitted configurations must keep working."""
        default = Factory.create(key="Connection")
        explicit = Factory.create(key="Connection", configuration={"host": "db"})

        self.assertEqual((default.host, default.port), ("localhost", 1))
        self.assertEqual(explicit.host, "db")

    def test_abstract_factory_accepts_model(self):
        """The type-constrained factory must spread a model the same way."""
        instance = AbstractFactory[Connection].create(
            key="Connection",
            configuration=ConnectionSettings(host="db", port=6543),
        )

        self.assertIsInstance(instance, Connection)
        self.assertEqual((instance.host, instance.port), ("db", 6543))

    def test_singleton_factory_accepts_model(self):
        """The singleton factory must build its cached instance from a model."""
        first = SingletonFactory.create(
            key="Connection",
            configuration=ConnectionSettings(host="db", port=6543),
        )

        self.assertEqual((first.host, first.port), ("db", 6543))
        self.assertIs(SingletonFactory.create(key="Connection"), first)

    def test_model_is_not_mutated(self):
        """Building from a model must leave the caller's model untouched."""
        settings = ConnectionSettings(host="db", port=6543)

        Factory.create(key="Connection", configuration=settings)

        self.assertEqual(settings.model_dump(), {"host": "db", "port": 6543})
