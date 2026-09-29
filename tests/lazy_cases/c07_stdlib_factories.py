from collections import namedtuple
from enum import Enum
from typing import NamedTuple
import dataclasses

Point = namedtuple("Point", "x y")
Color = Enum("Color", "RED GREEN")


class Typed(NamedTuple):
    x: int


@dataclasses.dataclass
class Data:
    x: int = 0
