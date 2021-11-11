from abc import ABC, abstractmethod
from datetime import timedelta

import pandas as pd
import numpy as np
from typing import Type, List, Union
from numbers import Number
from dataclasses import dataclass

from time_tools.forecasters import Forecaster


@dataclass
class Dispatch:
    """ Representation of dispatch -> both charge and discharge as
    as positive floats.

    Net charge is represented as single float where positive indicates discharge

    Charge and discharge are enforced as mutually exclusive in terms of their
    float values being above zero (I.e. Discharge should never occur at the
    same time as charge)
    """
    charge: float
    discharge: float

    @property
    def net_value(self):
        """ Representation of dispatch as single float where positive indicates
        discharge and negative indicates charge
        """
        return self.discharge - self.charge

    @property
    def no_dispatch(self):
        return self.net_value == 0.0

    @property
    def valid_dispatch(self) -> bool:
        """ Enforces property that charge and discharge are mutually exclusive.
        Null charge or discharge is expressed as float of value 0.0
        """
        if not min(self.charge, self.discharge) == 0.0:
            raise ValueError(
                'DispatchProposal attributes charge or discharge cannot'
                ' both be greater than 0.0'
            )
        elif self.charge < 0.0 or self.discharge < 0.0:
            raise ValueError(
                'DispatchProposal attributes charge or discharge cannot'
                ' be negative'
            )
        else:
            return True

    @classmethod
    def from_raw_float(cls, proposal: float):
        """ Create instance from raw float where positive value
        is interpreted as dispatch and negative dispatch interpreted as charge
        """
        return cls(
            charge=-min(0.0, proposal),
            discharge=max(0.0, proposal)
        )


@dataclass
class EquipmentMetadata:
    name: str
    capital_cost: float
    operational_cost: float


@dataclass
class Equipment(ABC):
    name: str
    report_on: List[str]

    def status(self) -> dict:
        return {x: getattr(self, x) for x in self.report_on}

    @abstractmethod
    def dispatch_request(
            self,
            proposal: Dispatch,
            sample_rate: timedelta
    ) -> Dispatch:
        pass


@dataclass
class Storage(Equipment):
    nominal_discharge_capacity: float
    nominal_charge_capacity: float
    storage_capacity: float
    round_trip_efficiency: float
    state_of_charge: float

    @property
    def available_energy(self):
        return self.state_of_charge * self.storage_capacity

    @property
    def available_storage(self):
        return self.storage_capacity * (1 - self.state_of_charge)

    @abstractmethod
    def dispatch_request(self, proposal: Dispatch, sample_rate: timedelta) -> Dispatch:
        pass

    @abstractmethod
    def update_state(self, energy):
        pass