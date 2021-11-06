from abc import abstractmethod, ABC
from dataclasses import dataclass
from typing import Type

from equipment import Storage, Equipment


@dataclass
class StateBasedProperty(ABC):
    @abstractmethod
    def calculate(self, state: Equipment):
        pass


@dataclass
class StateBasedCOP(StateBasedProperty):
    def calculate(self, state: Equipment) -> float:
        # Todo: insert model here
        return 4.0


@dataclass
class StateBasedCapacity(StateBasedProperty):
    nominal_capacity: float

    def calculate(self, state: Equipment) -> float:
        # Todo: insert model here
        calculated_capcity_factor = 1.0
        return self.nominal_capacity * calculated_capcity_factor
