from tests.lazy_cases.d04_base import Animal


class Dog(Animal):
    def __init__(self, n: int = 1):
        self.n = n


class NotAnAnimal:
    pass
