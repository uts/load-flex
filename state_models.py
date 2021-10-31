from abc import abstractmethod, ABC
from typing import Type

from equipment import Storage, Equipment


class StateBasedProperty(ABC):
    @staticmethod
    @abstractmethod
    def calculate(state: Equipment):
        pass


class StateBasedCOP(StateBasedProperty):
    @staticmethod
    def calculate(state: Equipment) -> float:
        # Todo: insert model here
        return 4.0


class StateBasedCapacity(StateBasedProperty):
    @staticmethod
    def calculate(state: Equipment) -> float:
        # Todo: insert model here
        return 2000
