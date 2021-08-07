from abc import ABC, abstractmethod
from pydantic import BaseModel
import pandas as pd
import numpy as np
from typing import Type, List, Union
from numbers import Number
from dataclasses import dataclass

from time_series_utils import Forecaster

class EquipmentMetadata:
    name: str
    capital_cost: float
    operational_cost: float


class Equipment(ABC):
    metadata: EquipmentMetadata
    dispatch_report: pd.DataFrame = None

    @abstractmethod
    def energy_request(self) -> float:
        pass


class Storage(Equipment):
    def __init__(
            self,
            metadata: EquipmentMetadata,
            discharge_capacity: float,
            charge_capacity: float,
            storage_capacity: float,
            state_of_charge: float,
            available_energy: float,
            round_trip_efficiency: float,
            dispatch_report: pd.DataFrame = None,
    ):
        super(Storage, self).__init__(metadata, dispatch_report)
        self.discharge_capacity = discharge_capacity
        self.charge_capacity = charge_capacity
        self.storage_capacity = storage_capacity
        self.state_of_charge = state_of_charge
        self.available_energy = available_energy
        self.round_trip_efficiency = round_trip_efficiency

        self.discharge_limit = self.discharge_capacity
        self.charge_limit = self.charge_capacity

    @abstractmethod
    def update_state(self):
        pass


class Battery(Storage):
    def update_state(self):
        pass

    def energy_request(self) -> float:

        return energy_exchange


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
