"""
Tests for the AbstractFactory class functionality.
"""

from unittest import TestCase

from sweet_tea.abstract_factory import AbstractFactory
from sweet_tea.registry import Registry
from sweet_tea.sweet_tea_error import SweetTeaError


class TestAbstractFactory(TestCase):
    """Test abstract factory with generics."""

    def setUp(self):
        """Clear registry before each test."""
        Registry._Registry__registry.clear()
        Registry._Registry__lookup.clear()
        Registry._Registry__lookup_keys.clear()

    def test_abstract_factory_creation(self):
        """Test creating an abstract factory with type parameter."""

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
        factory = AbstractFactory[BaseClass]

        # Should only see DerivedClass since it's a subclass of BaseClass
        instance = factory.create("derived", configuration={"value": "test"})
        self.assertIsInstance(instance, DerivedClass)
        self.assertEqual(instance.value, "test")

    def test_abstract_factory_filters_by_type(self):
        """Test that abstract factory only allows subclasses of the generic type."""

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
        animal_factory = AbstractFactory[Animal]
        dog = animal_factory.create("dog")
        cat = animal_factory.create("cat")

        self.assertIsInstance(dog, Dog)
        self.assertIsInstance(cat, Cat)
        self.assertEqual(dog.sound, "woof")
        self.assertEqual(cat.sound, "meow")

        # Car factory should not see Dog/Cat
        car_factory = AbstractFactory[Car]
        car = car_factory.create("car")
        self.assertIsInstance(car, Car)

    def test_abstract_factory_wrong_type(self):
        """Test that abstract factory rejects keys that don't match the type."""

        class Animal:
            pass

        class Dog(Animal):
            pass

        class Car:
            pass

        Registry.register("dog", Dog)
        Registry.register("car", Car)

        # Animal factory should not find "car"
        animal_factory = AbstractFactory[Animal]
        with self.assertRaises(SweetTeaError) as cm:
            animal_factory.create("car")
        self.assertIn("not present", str(cm.exception))

    def test_abstract_factory_generic_methods(self):
        """Test the generic type methods."""

        class TestClass:
            pass

        factory = AbstractFactory[TestClass]
        generic_type = factory._get_generic_type()

        self.assertEqual(generic_type, TestClass)

    def test_abstract_factory_with_filters(self):
        """Test abstract factory with library/label filters."""

        class BaseClass:
            pass

        class Impl1(BaseClass):
            pass

        class Impl2(BaseClass):
            pass

        Registry.register("impl", Impl1, "lib1")
        Registry.register("impl", Impl2, "lib2")

        factory = AbstractFactory[BaseClass]

        instance1 = factory.create("impl", library="lib1")
        instance2 = factory.create("impl", library="lib2")

        self.assertIsInstance(instance1, Impl1)
        self.assertIsInstance(instance2, Impl2)

    def test_abstract_factory_inheritance_hierarchy(self):
        """Test abstract factory with complex inheritance."""

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
        vehicle_factory = AbstractFactory[Vehicle]
        sedan = vehicle_factory.create("sedan")
        truck = vehicle_factory.create("truck")
        motorcycle = vehicle_factory.create("motorcycle")

        self.assertIsInstance(sedan, Sedan)
        self.assertIsInstance(truck, Truck)
        self.assertIsInstance(motorcycle, Motorcycle)

        # Car factory should only see Sedan (subclass of Car)
        car_factory = AbstractFactory[Car]
        sedan2 = car_factory.create("sedan")

        self.assertIsInstance(sedan2, Sedan)

        # Should not find truck in car factory
        with self.assertRaises(SweetTeaError):
            car_factory.create("truck")

    def test_abstract_factory_empty_registry(self):
        """Test abstract factory with no matching classes."""

        class TestClass:
            pass

        # Don't register anything
        factory = AbstractFactory[TestClass]

        with self.assertRaises(SweetTeaError) as cm:
            factory.create("anything")
        self.assertIn("not present", str(cm.exception))

    def test_abstract_factory_multiple_inheritance(self):
        """Test abstract factory with multiple inheritance."""

        class Interface1:
            pass

        class Interface2:
            pass

        class Implementation(Interface1, Interface2):
            pass

        Registry.register("impl", Implementation)

        # Should work with either interface
        factory1 = AbstractFactory[Interface1]
        factory2 = AbstractFactory[Interface2]

        instance1 = factory1.create("impl")
        instance2 = factory2.create("impl")

        self.assertIsInstance(instance1, Implementation)
        self.assertIsInstance(instance2, Implementation)
        self.assertIsInstance(instance1, Interface1)
        self.assertIsInstance(instance2, Interface2)
