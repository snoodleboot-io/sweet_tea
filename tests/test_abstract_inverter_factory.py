"""
Tests for the AbstractInverterFactory class functionality.
"""

from unittest import TestCase

from sweet_tea.abstract_inverter_factory import AbstractInverterFactory
from sweet_tea.registry import Registry
from sweet_tea.sweet_tea_error import SweetTeaError


class TestAbstractInverterFactory(TestCase):
    """Test abstract inverter factory with generics and class retrieval."""

    def setUp(self):
        """Clear registry before each test."""
        Registry._Registry__registry.clear()
        Registry._Registry__lookup.clear()
        Registry._Registry__lookup_keys.clear()

    def test_abstract_inverter_factory_creation(self):
        """Test creating an abstract inverter factory with type parameter."""

        class BaseClass:
            pass

        class DerivedClass(BaseClass):
            def __init__(self, value=None):
                self.value = value

        class UnrelatedClass:
            pass

        # Register classes
        Registry.register("derived", DerivedClass)
        Registry.register("unrelated", UnrelatedClass)

        # Create typed factory
        factory = AbstractInverterFactory[BaseClass]

        # Should only see DerivedClass since it's a subclass of BaseClass
        class_def = factory.create("derived")
        instance = class_def(value="test")
        self.assertIsInstance(instance, DerivedClass)
        self.assertEqual(instance.value, "test")

    def test_abstract_inverter_factory_filters_by_type(self):
        """Test that abstract inverter factory only allows subclasses of the generic type."""

        class Animal:
            pass

        class Dog(Animal):
            def __init__(self):
                self.sound = "woof"

        class Cat(Animal):
            def __init__(self):
                self.sound = "meow"

        class Car:
            pass

        # Register all classes
        Registry.register("dog", Dog)
        Registry.register("cat", Cat)
        Registry.register("car", Car)

        # Animal factory should only see Dog and Cat
        animal_factory = AbstractInverterFactory[Animal]
        dog_class = animal_factory.create("dog")
        cat_class = animal_factory.create("cat")

        dog = dog_class()
        cat = cat_class()

        self.assertIsInstance(dog, Dog)
        self.assertIsInstance(cat, Cat)
        self.assertEqual(dog.sound, "woof")
        self.assertEqual(cat.sound, "meow")

        # Car factory should not see Dog/Cat
        car_factory = AbstractInverterFactory[Car]
        car_class = car_factory.create("car")
        car = car_class()
        self.assertIsInstance(car, Car)

    def test_abstract_inverter_factory_wrong_type(self):
        """Test that abstract inverter factory rejects keys that don't match the type."""

        class Animal:
            pass

        class Dog(Animal):
            pass

        class Car:
            pass

        Registry.register("dog", Dog)
        Registry.register("car", Car)

        # Animal factory should not find "car"
        animal_factory = AbstractInverterFactory[Animal]
        with self.assertRaises(SweetTeaError) as cm:
            animal_factory.create("car")
        self.assertIn("not present", str(cm.exception))

    def test_abstract_inverter_factory_generic_methods(self):
        """Test the generic type methods."""

        class TestClass:
            pass

        factory = AbstractInverterFactory[TestClass]
        generic_type = factory._get_generic_type()

        self.assertEqual(generic_type, TestClass)

    def test_abstract_inverter_factory_with_filters(self):
        """Test abstract inverter factory with library/label filters."""

        class BaseClass:
            pass

        class Impl1(BaseClass):
            pass

        class Impl2(BaseClass):
            pass

        Registry.register("impl", Impl1, "lib1")
        Registry.register("impl", Impl2, "lib2")

        factory = AbstractInverterFactory[BaseClass]

        class_def1 = factory.create("impl", library="lib1")
        class_def2 = factory.create("impl", library="lib2")

        instance1 = class_def1()
        instance2 = class_def2()

        self.assertIsInstance(instance1, Impl1)
        self.assertIsInstance(instance2, Impl2)

    def test_abstract_inverter_factory_inheritance_hierarchy(self):
        """Test abstract inverter factory with complex inheritance."""

        class Vehicle:
            pass

        class Car(Vehicle):
            pass

        class Truck(Vehicle):
            pass

        class Sedan(Car):
            pass

        class Motorcycle(Vehicle):
            pass

        # Register all
        Registry.register("sedan", Sedan)
        Registry.register("truck", Truck)
        Registry.register("motorcycle", Motorcycle)

        # Vehicle factory should see all
        vehicle_factory = AbstractInverterFactory[Vehicle]
        sedan_class = vehicle_factory.create("sedan")
        truck_class = vehicle_factory.create("truck")
        motorcycle_class = vehicle_factory.create("motorcycle")

        sedan = sedan_class()
        truck = truck_class()
        motorcycle = motorcycle_class()

        self.assertIsInstance(sedan, Sedan)
        self.assertIsInstance(truck, Truck)
        self.assertIsInstance(motorcycle, Motorcycle)

        # Car factory should only see Sedan (subclass of Car)
        car_factory = AbstractInverterFactory[Car]
        sedan_class2 = car_factory.create("sedan")
        sedan2 = sedan_class2()

        self.assertIsInstance(sedan2, Sedan)

        # Should not find truck in car factory
        with self.assertRaises(SweetTeaError):
            car_factory.create("truck")

    def test_abstract_inverter_factory_empty_registry(self):
        """Test abstract inverter factory with no matching classes."""

        class TestClass:
            pass

        # Don't register anything
        factory = AbstractInverterFactory[TestClass]

        with self.assertRaises(SweetTeaError) as cm:
            factory.create("anything")
        self.assertIn("not present", str(cm.exception))

    def test_abstract_inverter_factory_multiple_inheritance(self):
        """Test abstract inverter factory with multiple inheritance."""

        class Interface1:
            pass

        class Interface2:
            pass

        class Implementation(Interface1, Interface2):
            pass

        Registry.register("impl", Implementation)

        # Should work with either interface
        factory1 = AbstractInverterFactory[Interface1]
        factory2 = AbstractInverterFactory[Interface2]

        class_def1 = factory1.create("impl")
        class_def2 = factory2.create("impl")

        instance1 = class_def1()
        instance2 = class_def2()

        self.assertIsInstance(instance1, Implementation)
        self.assertIsInstance(instance2, Implementation)
        self.assertIsInstance(instance1, Interface1)
        self.assertIsInstance(instance2, Interface2)

    def test_abstract_inverter_factory_case_insensitive_key(self):
        """Test case insensitive key matching."""

        class BaseClass:
            pass

        class TestClass(BaseClass):
            def __init__(self, value="default"):
                self.value = value

        Registry.register("test_class", TestClass)

        factory = AbstractInverterFactory[BaseClass]

        # Try different case variations
        class_def1 = factory.create("TEST_CLASS")
        class_def2 = factory.create("TestClass")
        class_def3 = factory.create("test_class")

        # All should return the same class definition
        self.assertEqual(class_def1, TestClass)
        self.assertEqual(class_def2, TestClass)
        self.assertEqual(class_def3, TestClass)

        # And should be instantiable
        instance = class_def1(value="test")
        self.assertIsInstance(instance, TestClass)
        self.assertEqual(instance.value, "test")

    def test_abstract_inverter_factory_lazy_construction(self):
        """Test lazy construction pattern with abstract inverter factory."""

        class Service:
            def __init__(self, config=None):
                self.config = config or {}
                self.initialized = True

        class DatabaseService(Service):
            pass

        Registry.register("database", DatabaseService)

        factory = AbstractInverterFactory[Service]

        # Get class definition without instantiating
        db_class = factory.create("database")

        # Should be able to instantiate later with different configs
        db1 = db_class(config={"host": "prod"})
        db2 = db_class(config={"host": "test"})

        self.assertIsInstance(db1, DatabaseService)
        self.assertIsInstance(db2, DatabaseService)
        self.assertEqual(db1.config["host"], "prod")
        self.assertEqual(db2.config["host"], "test")
        self.assertNotEqual(db1, db2)  # Different instances
