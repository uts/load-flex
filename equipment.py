from abc import ABC, abstractmethod
import pandas as pd
import numpy as np
from typing import Type, List, Union, Tuple
from numbers import Number
from dataclasses import dataclass

from time_series_utils import Forecaster


@dataclass
class EquipmentMetadata:
    name: str
    capital_cost: float
    operational_cost: float


@dataclass
class Equipment(ABC):
    name: str

    def status(self) -> dict:
        return {x: getattr(self, x) for x in self.report_on}

    @abstractmethod
    def energy_request(self, energy) -> float:
        pass

    @abstractmethod
    def update_state(self, energy):
        pass


@dataclass
class Storage(Equipment):
    nominal_discharge_capacity: float
    nominal_charge_capacity: float
    storage_capacity: float
    state_of_charge: float
    round_trip_efficiency: float
    dispatch_report: pd.DataFrame

    @property
    def available_energy(self):
        return self.state_of_charge * self.storage_capacity

    @property
    def available_storage(self):
        return self.storage_capacity * (1 - self.state_of_charge)

    @abstractmethod
    def energy_request(self, energy) -> float:
        pass

    @abstractmethod
    def update_state(self, energy):
        pass


@dataclass
class Dispatcher(ABC):
    demand_arr: Union[List[Number], np.ndarray, pd.Series]
    equipment: List[Type[Equipment]]
    forecaster: Type[Forecaster]
    remaining_demand_arr: np.ndarray = None

    @abstractmethod
    def dispatch(self):
        pass


class BasicDispatcher(Dispatcher):
    def dispatch(self):
        self.remaining_demand_arr = self.demand_arr.to_numpy()
        for plant in self.equipment:
            plant.dispatch()
            self.remaining_demand_arr -= plant.dispatch_arr


