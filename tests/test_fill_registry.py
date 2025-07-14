from sweet_tea.registry import Registry
from classes_for_testing.asdf.a import A

def test_fill_registry():
    for entry in Registry.entries():
        print(entry)

if __name__ == '__main__':
    test_fill_registry()
