"""
Regression tests for SWE-5: SingletonFactory cached against the caller's key spelling
rather than the resolved registry entry, so each spelling produced its own instance.
"""

from unittest import TestCase

from sweet_tea.registry import Registry
from sweet_tea.singleton_factory import SingletonFactory
from sweet_tea.sweet_tea_error import SweetTeaError


class PostgresConnection:
    """Stand-in for a resource that must genuinely exist only once."""

    def __init__(self, host: str = "localhost") -> None:
        self.host = host


class RedisConnection:
    """Second class sharing a key with the first, under a different library."""

    def __init__(self, host: str = "localhost") -> None:
        self.host = host


class TestSingletonIdentity(TestCase):
    """One registry entry must map to exactly one cached instance."""

    def setUp(self):
        """Clear both the registry and the singleton cache."""
        Registry._Registry__registry.clear()
        Registry._Registry__lookup.clear()
        Registry._Registry__lookup_keys.clear()
        SingletonFactory.clear()

    def test_key_spellings_share_one_instance(self):
        """Every spelling that resolves to one entry must return one instance."""
        Registry.register(key="PostgresConnection", class_def=PostgresConnection)

        first = SingletonFactory.create(key="PostgresConnection")
        for spelling in (
            "postgresconnection",
            "postgres_connection",
            "POSTGRESCONNECTION",
        ):
            self.assertIs(
                SingletonFactory.create(key=spelling),
                first,
                f"spelling {spelling!r} produced a second instance",
            )

    def test_spellings_do_not_multiply_cache_slots(self):
        """The cache must hold one slot, not one per spelling."""
        Registry.register(key="PostgresConnection", class_def=PostgresConnection)

        SingletonFactory.create(key="PostgresConnection")
        SingletonFactory.create(key="postgres_connection")

        self.assertEqual(SingletonFactory.list_singletons(), ["postgresconnection"])

    def test_configuration_from_first_call_wins(self):
        """A later spelling must not silently reconstruct with new configuration."""
        Registry.register(key="PostgresConnection", class_def=PostgresConnection)

        first = SingletonFactory.create(
            key="PostgresConnection", configuration={"host": "primary"}
        )
        second = SingletonFactory.create(
            key="postgres_connection", configuration={"host": "replica"}
        )

        self.assertIs(second, first)
        self.assertEqual(second.host, "primary")

    def test_same_key_different_libraries_stay_separate(self):
        """Entries differing only by library must not share a cache slot."""
        Registry.register(key="Conn", class_def=PostgresConnection, library="postgres")
        Registry.register(key="Conn", class_def=RedisConnection, library="redis")

        postgres = SingletonFactory.create(key="Conn", library="postgres")
        redis = SingletonFactory.create(key="Conn", library="redis")

        self.assertIsNot(postgres, redis)
        self.assertIsInstance(postgres, PostgresConnection)
        self.assertIsInstance(redis, RedisConnection)

    def test_same_key_different_labels_stay_separate(self):
        """Entries differing only by label must not share a cache slot."""
        Registry.register(
            key="Conn", class_def=PostgresConnection, library="db", label="prod"
        )
        Registry.register(
            key="Conn", class_def=RedisConnection, library="db", label="test"
        )

        prod = SingletonFactory.create(key="Conn", library="db", label="prod")
        test = SingletonFactory.create(key="Conn", library="db", label="test")

        self.assertIsNot(prod, test)

    def test_ambiguous_key_raises_rather_than_guessing(self):
        """Without a filter, an ambiguous key must not silently pick one entry."""
        Registry.register(key="Conn", class_def=PostgresConnection, library="postgres")
        Registry.register(key="Conn", class_def=RedisConnection, library="redis")

        with self.assertRaises(SweetTeaError):
            SingletonFactory.create(key="Conn")

    def test_pop_accepts_any_spelling(self):
        """Popping by a different spelling must remove the cached instance."""
        Registry.register(key="PostgresConnection", class_def=PostgresConnection)
        created = SingletonFactory.create(key="PostgresConnection")

        removed = SingletonFactory.pop(key="postgres_connection")

        self.assertIs(removed, created)
        self.assertEqual(SingletonFactory.list_singletons(), [])

    def test_pop_respects_filters(self):
        """Popping one library must leave the other library's instance cached."""
        Registry.register(key="Conn", class_def=PostgresConnection, library="postgres")
        Registry.register(key="Conn", class_def=RedisConnection, library="redis")
        SingletonFactory.create(key="Conn", library="postgres")
        redis = SingletonFactory.create(key="Conn", library="redis")

        SingletonFactory.pop(key="Conn", library="postgres")

        self.assertEqual(SingletonFactory.list_singletons(), ["conn"])
        self.assertIs(SingletonFactory.create(key="Conn", library="redis"), redis)

    def test_pop_uncached_key_raises(self):
        """Popping a registered but never-created key is still an error."""
        Registry.register(key="PostgresConnection", class_def=PostgresConnection)

        with self.assertRaises(SweetTeaError):
            SingletonFactory.pop(key="PostgresConnection")

    def test_pop_unregistered_key_raises(self):
        """Popping a key that was never registered is an error, not a crash."""
        with self.assertRaises(SweetTeaError):
            SingletonFactory.pop(key="NeverHeardOfIt")
