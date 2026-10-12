"""The in-tree bases every other case inherits from, by one spelling or another."""

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

T = TypeVar("T")


class Shape(ABC):
    """The ABC a caller narrows on."""

    @abstractmethod
    def area(self) -> int: ...


class Container(Generic[T]):
    """A generic base, so a subscripted base has something real to name."""
