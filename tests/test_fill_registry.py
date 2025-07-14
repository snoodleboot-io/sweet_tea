from sweet_tea.factory import Factory
from sweet_tea.registry import Registry
from classes_for_testing.asdf.a import A

def test_fill_registry():
    for entry in Registry.entries():
        print(entry)

def create_a():
    a = Factory.create(key='a', configuration={})
    a.print()

if __name__ == '__main__':
    test_fill_registry()

    create_a()
