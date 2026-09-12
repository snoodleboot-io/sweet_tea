"""
Tests for SWE-8: a registered class may declare ``__configuration__``, a pydantic model
its configuration is validated against before construction.
"""

from unittest import TestCase

from pydantic import BaseModel, ConfigDict, ValidationError

from sweet_tea.abstract_factory import AbstractFactory
from sweet_tea.factory import Factory
from sweet_tea.inverter_factory import InverterFactory
from sweet_tea.registry import Registry
from sweet_tea.singleton_factory import SingletonFactory
from sweet_tea.sweet_tea_error import SweetTeaError


class PoolSettings(BaseModel):
    """Nested model, used to prove validated nested values keep their type."""

    size: int = 5


class PgSettings(BaseModel):
    """Declared configuration for PgConnection."""

    host: str
    port: int = 5432
    pool: PoolSettings = PoolSettings()


class StrictPgSettings(PgSettings):
    """Declared configuration that rejects undeclared keys."""

    model_config = ConfigDict(extra="forbid")


class OtherSettings(BaseModel):
    """A model unrelated to PgSettings but carrying compatible fields."""

    host: str
    port: str


class Connection:
    """Undeclared base class; must keep today's unvalidated behavior."""

    def __init__(self, host: str = "localhost", port: object = 1) -> None:
        self.host = host
        self.port = port


class PgConnection(Connection):
    """Declares PgSettings as its configuration."""

    __configuration__ = PgSettings

    def __init__(self, host: str, port: int, pool: PoolSettings | None = None) -> None:
        super().__init__(host=host, port=port)
        self.pool = pool


class StrictPgConnection(PgConnection):
    """Declares a configuration model that forbids extra keys."""

    __configuration__ = StrictPgSettings


class ReplicaConnection(PgConnection):
    """Inherits PgConnection's declaration without restating it."""


class BadlyDeclaredConnection(Connection):
    """Declares something that is not a BaseModel subclass."""

    __configuration__ = dict


class TestDeclaredConfiguration(TestCase):
    """Configuration must be validated against a declared model before construction."""

    def setUp(self):
        """Clear both the registry and the singleton cache."""
        Registry._Registry__registry.clear()
        Registry._Registry__lookup.clear()
        Registry._Registry__lookup_keys.clear()
        SingletonFactory.clear()
        for class_def in (
            Connection,
            PgConnection,
            StrictPgConnection,
            ReplicaConnection,
            BadlyDeclaredConnection,
        ):
            Registry.register(key=class_def.__name__, class_def=class_def)

    def test_dict_configuration_is_coerced(self):
        """Dict values must be coerced to the declared field types."""
        instance = Factory.create(
            key="PgConnection", configuration={"host": "db", "port": "6543"}
        )

        self.assertEqual((instance.host, instance.port), ("db", 6543))

    def test_declared_defaults_apply(self):
        """Fields omitted by the caller must receive the declared model's defaults."""
        instance = Factory.create(key="PgConnection", configuration={"host": "db"})

        self.assertEqual(instance.port, 5432)
        self.assertIsInstance(instance.pool, PoolSettings)

    def test_invalid_value_raises_sweet_tea_error(self):
        """A value the model rejects must raise SweetTeaError naming the key."""
        with self.assertRaises(SweetTeaError) as raised:
            Factory.create(
                key="PgConnection",
                configuration={"host": "db", "port": "not-a-port"},
            )

        self.assertIn("pgconnection", str(raised.exception))
        self.assertIn("PgSettings", str(raised.exception))
        self.assertIn("port", str(raised.exception))

    def test_validation_error_is_chained(self):
        """The original ValidationError must be preserved as the cause."""
        with self.assertRaises(SweetTeaError) as raised:
            Factory.create(key="PgConnection", configuration={"port": 1})

        self.assertIsInstance(raised.exception.__cause__, ValidationError)

    def test_missing_configuration_is_validated(self):
        """Omitting configuration must still enforce required fields."""
        with self.assertRaises(SweetTeaError) as raised:
            Factory.create(key="PgConnection")

        self.assertIn("host", str(raised.exception))

    def test_declared_model_instance_is_used_as_is(self):
        """An instance of the declared model must not be re-validated or copied."""
        pool = PoolSettings(size=20)

        instance = Factory.create(
            key="PgConnection",
            configuration=PgSettings(host="db", pool=pool),
        )

        self.assertIs(instance.pool, pool)

    def test_other_model_is_validated_into_declared_model(self):
        """A different model must be validated, so its values are coerced too."""
        instance = Factory.create(
            key="PgConnection",
            configuration=OtherSettings(host="db", port="6543"),
        )

        self.assertEqual(instance.port, 6543)

    def test_extra_keys_ignored_by_default(self):
        """Undeclared keys follow pydantic's default and are dropped, not passed on."""
        instance = Factory.create(
            key="PgConnection", configuration={"host": "db", "hostname": "typo"}
        )

        self.assertEqual(instance.host, "db")

    def test_extra_keys_rejected_when_model_forbids(self):
        """A model with extra="forbid" must turn undeclared keys into an error."""
        with self.assertRaises(SweetTeaError) as raised:
            Factory.create(
                key="StrictPgConnection",
                configuration={"host": "db", "hostname": "typo"},
            )

        self.assertIn("hostname", str(raised.exception))

    def test_declaration_is_inherited(self):
        """A subclass must inherit its parent's declared configuration."""
        instance = Factory.create(
            key="ReplicaConnection", configuration={"host": "db", "port": "7"}
        )

        self.assertEqual(instance.port, 7)

    def test_non_model_declaration_raises(self):
        """A __configuration__ that is not a BaseModel subclass must be reported."""
        with self.assertRaises(SweetTeaError) as raised:
            Factory.create(key="BadlyDeclaredConnection")

        self.assertIn(
            "BadlyDeclaredConnection.__configuration__", str(raised.exception)
        )

    def test_undeclared_class_is_not_validated(self):
        """Classes without __configuration__ must behave exactly as before."""
        instance = Factory.create(key="Connection", configuration={"port": "6543"})

        self.assertEqual(instance.port, "6543")

    def test_abstract_factory_validates(self):
        """The type-constrained factory must validate through the same path."""
        instance = AbstractFactory[Connection].create(
            key="PgConnection", configuration={"host": "db", "port": "6543"}
        )

        self.assertIsInstance(instance, PgConnection)
        self.assertEqual(instance.port, 6543)

    def test_singleton_factory_validates_on_construction(self):
        """The singleton factory must validate the configuration it builds from."""
        with self.assertRaises(SweetTeaError):
            SingletonFactory.create(key="PgConnection", configuration={"port": 1})

        instance = SingletonFactory.create(
            key="PgConnection", configuration={"host": "db", "port": "6543"}
        )

        self.assertEqual(instance.port, 6543)

    def test_failed_singleton_validation_caches_nothing(self):
        """A rejected configuration must not leave a cached instance behind."""
        with self.assertRaises(SweetTeaError):
            SingletonFactory.create(key="PgConnection")

        self.assertEqual(SingletonFactory.list_singletons(), [])

    def test_inverter_factory_does_not_validate(self):
        """InverterFactory returns the class and must not touch the declaration."""
        self.assertIs(
            InverterFactory.create(key="BadlyDeclaredConnection"),
            BadlyDeclaredConnection,
        )
