"""
Tests for the SingletonFactory class functionality.
"""

from unittest import TestCase

from sweet_tea.registry import Registry
from sweet_tea.singleton_factory import SingletonFactory


class TestService:
    """Test service class for singleton factory tests."""

    def __init__(self, name="test"):
        self.name = name


class TestSingletonFactory(TestCase):
    """Test singleton factory operations."""

    def setUp(self):
        """Clear singleton registry before each test."""
        SingletonFactory.clear()
        # Register test service in registry
        Registry.register("testservice", TestService)

    def test_create_singleton(self):
        """Test creating singleton instances via create method."""
        # Create singleton instance
        service1 = SingletonFactory.create(
            "testservice", configuration={"name": "my-service"}
        )
        self.assertEqual(service1.name, "my-service")

        # Retrieve the same instance (should return cached)
        service2 = SingletonFactory.create("testservice")
        self.assertIs(service1, service2)
        self.assertEqual(service2.name, "my-service")

    def test_create_different_configs(self):
        """Test that different keys create different singletons."""
        service1 = SingletonFactory.create(
            "testservice", configuration={"name": "service1"}
        )
        service2 = SingletonFactory.create(
            "testservice", configuration={"name": "service2"}
        )

        # Should be the same instance since same key
        self.assertIs(service1, service2)
        self.assertEqual(service1.name, "service1")  # First config wins

    def test_clear_instances(self):
        """Test clearing all instances."""
        SingletonFactory.create("testservice")
        self.assertEqual(len(SingletonFactory.list_singletons()), 1)

        SingletonFactory.clear()
        self.assertEqual(len(SingletonFactory.list_singletons()), 0)

    def test_pop_instance(self):
        """Test removing singleton instances."""
        service = SingletonFactory.create("testservice")
        self.assertEqual(len(SingletonFactory.list_singletons()), 1)

        removed = SingletonFactory.pop("testservice")
        self.assertIs(removed, service)
        self.assertEqual(len(SingletonFactory.list_singletons()), 0)

    def test_list_keys(self):
        """Test listing available registry keys."""
        keys = SingletonFactory.list_keys()
        self.assertIn("testservice", keys)

    def test_list_singletons(self):
        """Test listing cached singleton keys."""
        SingletonFactory.create("testservice")
        singletons = SingletonFactory.list_singletons()
        self.assertEqual(singletons, ["testservice"])

    def test_thread_safety(self):
        """Test that create operations are thread-safe."""
        import threading
        import time

        results = []
        errors = []

        def worker(thread_id):
            try:
                # Create singleton for this thread's key
                key = f"service_{thread_id}"
                Registry.register(key, TestService)

                service1 = SingletonFactory.create(
                    key, configuration={"name": f"thread_{thread_id}"}
                )

                # Small delay to increase chance of race conditions
                time.sleep(0.001)

                # Get the same instance again
                service2 = SingletonFactory.create(key)
                if service1 is service2 and service1.name == f"thread_{thread_id}":
                    results.append(thread_id)
                else:
                    errors.append(f"Thread {thread_id}: Instance mismatch")

            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        # Start multiple threads
        threads = []
        for i in range(5):
            thread = threading.Thread(target=worker, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify no errors occurred
        self.assertEqual(len(errors), 0, f"Threading errors: {errors}")
        self.assertEqual(len(results), 5, "All threads should succeed")
