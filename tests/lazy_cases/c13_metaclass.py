class Meta(type):
    pass


class WithMeta(metaclass=Meta):
    pass


import abc


class AbstractThing(abc.ABC):
    @abc.abstractmethod
    def go(self): ...
