from sweet_tea.abstract_factory import AbstractFactory
from sweet_tea.factory import Factory
from sweet_tea.registry import Registry
from classes_for_testing.asdf.a import A

def test_fill_registry():
    for entry in Registry.entries():
        print(entry)

def create_a():
    a = Factory.create(key='a', configuration={})
    a.print()

def create_b():
    factory = AbstractFactory[A]
    b = factory.create(key='b', configuration={})
    b.print()

if __name__ == '__main__':
    test_fill_registry()

    create_a()

    create_b()
