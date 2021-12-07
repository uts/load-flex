from __future__ import annotations

from abc import ABC, abstractmethod, abstractproperty
from datetime import timedelta

from typing import List
from dataclasses import dataclass


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

    def validate(self):
        """ Enforces property that charge and discharge are mutually exclusive.
        Null charge or discharge is expressed as float of value 0.0
        """

        if self.charge < 0.0 or self.discharge < 0.0:
            raise ValueError(
                'DispatchProposal attributes charge or discharge cannot'
                ' be negative'
            )

        if not min(self.charge, self.discharge) == 0.0:
            raise ValueError(
                'Dispatch charge and discharge cannot'
                ' both be greater than 0.0'
            )

    def to_thermal(self, cop: float) -> ThermalDispatch:
        return ThermalDispatch(
            charge=self.charge * cop,
            discharge=self.discharge * cop,
            coefficient_of_performance=cop
        )

    @classmethod
    def from_raw_float(cls, dispatch_value: float):
        """ Create instance from raw float where positive value
        is interpreted as dispatch and negative dispatch interpreted as charge
        """
        return cls(
            charge=-min(0.0, dispatch_value),
            discharge=max(0.0, dispatch_value)
        )


@dataclass
class ThermalDispatch(Dispatch):
    coefficient_of_performance: float

    def to_electrical(self, cop: float = None) -> Dispatch:
        """ Convert thermal dispatch into equivalent electrical dispatch
        based on COP
        """
        if not cop:
            cop = self.coefficient_of_performance
        return Dispatch(
            self.charge / cop,
            self.discharge / cop
        )


@dataclass
class SubstitutionDispatch(Dispatch):
    """ Represents the replacement of one type of dispatch with another
    (e.g. electric hot water replaced by heat pump).

    Dispatch must be same type such that summation of charge and discharge is meaningful
    (e.g. electric and electric, thermal and thermal, or gas and gas)

    Unlike normal Dispatch, it is expected that charge and discharge are mutually inclusive
    but their rates reflect the difference in efficiency/performance of the baseline and
    substitute supply
    """
    @classmethod
    def from_dispatches(cls, base_dispatch, sub_dispatch):
        """ Instantiate SubstitutionDispatch - base_dispatch replacement is equivalent to
        discharge (it indicates quantum removed from load curve), sub_dispatch is
        equivalent to charge (indicates quantum added to load curve)
        """
        return cls(
            sub_dispatch,
            base_dispatch
        )

    def validate(self):
        """ Enforces property that charge and discharge are mutually inlcusive.
        Null charge or discharge is expressed as float of value 0.0
        """

        if self.charge < 0.0 or self.discharge < 0.0:
            raise ValueError(
                'DispatchProposal attributes charge or discharge cannot'
                ' be negative'
            )

        if all([
            not self.charge == self.discharge == 0.0,
            self.charge * self.discharge == 0.0
        ]):
            raise ValueError(
                'Substitution charge and discharge are mutually inclusive - '
                ' they must both be greater than 0.0, or both be equal to 0.0'
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

    @property
    @abstractmethod
    def input_capacity(self):
        pass

    @property
    @abstractmethod
    def output_capacity(self):
        pass

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
    def input_capacity(self):
        return self.nominal_charge_capacity

    @property
    def output_capacity(self):
        return self.nominal_discharge_capacity

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
