"""
Tests for the SingletonFactory class functionality.
"""

from unittest import TestCase

from sweet_tea.singleton_factory import SingletonFactory
from sweet_tea.sweet_tea_error import SweetTeaError


class TestSingletonFactory(TestCase):
    """Test singleton factory operations."""

    def setUp(self):
        """Clear singleton registry before each test."""
        SingletonFactory.clear()

    def test_register_and_get(self):
        """Test registering and retrieving singleton instances."""

        class TestService:
            def __init__(self, name):
                self.name = name

        service = TestService("my-service")
        SingletonFactory.register("test_service", service)

        # Retrieve the same instance
        retrieved = SingletonFactory.get("test_service")
        self.assertIs(retrieved, service)
        self.assertEqual(retrieved.name, "my-service")

    def test_has_instance(self):
        """Test checking if an instance is registered."""

        class TestService:
            pass

        service = TestService()
        SingletonFactory.register("test", service)

        self.assertTrue(SingletonFactory.has("test"))
        self.assertFalse(SingletonFactory.has("nonexistent"))

    def test_case_insensitive_keys(self):
        """Test that keys are case-insensitive."""

        class TestService:
            pass

        service = TestService()
        SingletonFactory.register("TestService", service)

        # Should work with different cases
        self.assertTrue(SingletonFactory.has("testservice"))
        self.assertTrue(SingletonFactory.has("TESTSERVICE"))
        self.assertTrue(SingletonFactory.has("TestService"))

        retrieved = SingletonFactory.get("testservice")
        self.assertIs(retrieved, service)

    def test_register_duplicate_without_override(self):
        """Test that registering duplicate keys raises error."""

        class TestService:
            pass

        service1 = TestService()
        service2 = TestService()

        SingletonFactory.register("test", service1)

        with self.assertRaises(SweetTeaError) as cm:
            SingletonFactory.register("test", service2)

        self.assertIn("already registered", str(cm.exception))

    def test_register_duplicate_with_override(self):
        """Test registering duplicate keys with allow_override=True."""

        class TestService:
            def __init__(self, value):
                self.value = value

        service1 = TestService(1)
        service2 = TestService(2)

        SingletonFactory.register("test", service1)
        SingletonFactory.register("test", service2, allow_override=True)

        retrieved = SingletonFactory.get("test")
        self.assertIs(retrieved, service2)
        self.assertEqual(retrieved.value, 2)

    def test_get_nonexistent(self):
        """Test getting nonexistent instance raises error."""
        with self.assertRaises(SweetTeaError) as cm:
            SingletonFactory.get("nonexistent")

        self.assertIn("No singleton instance registered", str(cm.exception))
        self.assertIn("Available keys: []", str(cm.exception))

    def test_get_nonexistent_with_available_keys(self):
        """Test error message includes available keys."""

        class TestService:
            pass

        SingletonFactory.register("service1", TestService())
        SingletonFactory.register("service2", TestService())

        with self.assertRaises(SweetTeaError) as cm:
            SingletonFactory.get("nonexistent")

        error_msg = str(cm.exception)
        self.assertIn("Available keys: ['service1', 'service2']", error_msg)

    def test_unregister_existing(self):
        """Test unregistering existing instance."""

        class TestService:
            pass

        service = TestService()
        SingletonFactory.register("test", service)

        self.assertTrue(SingletonFactory.has("test"))

        result = SingletonFactory.unregister("test")
        self.assertTrue(result)
        self.assertFalse(SingletonFactory.has("test"))

    def test_unregister_nonexistent(self):
        """Test unregistering nonexistent instance."""
        result = SingletonFactory.unregister("nonexistent")
        self.assertFalse(result)

    def test_clear_instances(self):
        """Test clearing all instances."""

        class TestService:
            pass

        SingletonFactory.register("service1", TestService())
        SingletonFactory.register("service2", TestService())

        self.assertEqual(SingletonFactory.count(), 2)

        SingletonFactory.clear()

        self.assertEqual(SingletonFactory.count(), 0)
        self.assertEqual(SingletonFactory.list_keys(), [])

    def test_list_keys(self):
        """Test listing registered keys."""

        class TestService:
            pass

        # Register in non-alphabetical order
        SingletonFactory.register("zebra", TestService())
        SingletonFactory.register("alpha", TestService())
        SingletonFactory.register("beta", TestService())

        keys = SingletonFactory.list_keys()
        self.assertEqual(keys, ["alpha", "beta", "zebra"])

    def test_count_instances(self):
        """Test counting registered instances."""

        class TestService:
            pass

        self.assertEqual(SingletonFactory.count(), 0)

        SingletonFactory.register("service1", TestService())
        self.assertEqual(SingletonFactory.count(), 1)

        SingletonFactory.register("service2", TestService())
        self.assertEqual(SingletonFactory.count(), 2)

        SingletonFactory.clear()
        self.assertEqual(SingletonFactory.count(), 0)

    def test_thread_safety(self):
        """Test that operations are thread-safe."""
        import threading
        import time

        results = []
        errors = []

        def worker(thread_id):
            try:

                class TestService:
                    def __init__(self, tid):
                        self.thread_id = tid

                # Register instance
                service = TestService(thread_id)
                key = f"service_{thread_id}"
                SingletonFactory.register(key, service)

                # Small delay to increase chance of race conditions
                time.sleep(0.001)

                # Verify we can retrieve it
                retrieved = SingletonFactory.get(key)
                if retrieved is service:
                    results.append(thread_id)
                else:
                    errors.append(f"Wrong instance for {thread_id}")

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

        # Verify all registrations succeeded
        self.assertEqual(SingletonFactory.count(), 5)

        # Verify all instances are correct
        self.assertEqual(len(results), 5)
