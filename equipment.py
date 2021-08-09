from abc import ABC, abstractmethod
from pydantic import BaseModel
import pandas as pd
import numpy as np
from typing import Type, List, Union
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
    metadata: EquipmentMetadata

    @abstractmethod
    def energy_request(self, energy) -> float:
        pass


@dataclass
class Storage(Equipment):
    discharge_capacity: float
    charge_capacity: float
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
    def update_state(self, energy):
        pass


class Battery(Storage):
    def update_state(self, energy: float):
        if energy > 0:
            # Apply efficiency on charge only
            energy = self.round_trip_efficiency * energy
        self.state_of_charge += energy / self.storage_capacity

    def energy_request(self, energy) -> float:
        # Negative energy indicates discharge
        # Positive energy indicate charge
        if energy < 0:
            energy_exchange = - min(
                abs(energy),
                self.discharge_capacity,
                self.available_energy
            )
        else:
            energy_exchange = min(
                energy,
                self.available_storage,
                self.charge_capacity
            )
        self.update_state(energy_exchange)
        return energy_exchange


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
