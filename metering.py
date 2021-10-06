from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta, datetime
from typing import Union, Dict
from abc import abstractmethod, ABC

import pandas as pd
import numpy as np
from ts_tariffs.sites import Validator, ElectricityMeterData, MeterData


@dataclass
class DispatchFlexMeter(ABC):
    dispatch_ts: pd.DataFrame = None
    flexed_meter_ts: pd.DataFrame = None

    @abstractmethod
    def calculate_flexed_demand(
            self,
            name: str,
    ):
        pass

    def update_dispatch(
            self,
            dt: datetime,
            charge: float,
            discharge: float,
            other: Dict[str, float] = None
    ):
        self.dispatch_ts['charge'].loc[dt] = charge
        self.dispatch_ts['discharge'].loc[dt] = discharge
        if other:
            for key, value in other.items():
                self.dispatch_ts[key] = value


@dataclass
class PowerFlexMeter(DispatchFlexMeter, ElectricityMeterData):
    """
    """

    def __post_init__(self):
        self.dispatch_ts = pd.DataFrame(index=self.meter_ts.index)
        self.flexed_meter_ts = pd.DataFrame(index=self.meter_ts.index)

    def calculate_flexed_demand(
            self,
            name,
    ):
        """ Adjust power, apparent power profiles according to a
         change in demand energy
        """
        self.flexed_meter_ts = self.meter_ts.copy()
        self.flexed_meter_ts['demand_energy'] += \
            self.dispatch_ts['charge'] + \
            self.dispatch_ts['discharge']
        delta_power = self.dispatch_ts * self.sample_rate / timedelta(hours=1)
        self.flexed_meter_ts['demand_power'] += delta_power['charge'] + delta_power['discharge']
        self.flexed_meter_ts['demand_apparent'] += self.flexed_meter_ts['demand_power'] / self.meter_ts['power_factor']
        

@dataclass
class ThermalLoadProperties:
    coefficient_of_performance: Union[float, np.ndarray]
    charge_as: str
    discharge_as: str


@dataclass
class ThermalLoadFlexMeter(
    DispatchFlexMeter,
    ThermalLoadProperties,
    ThermalLoadProperties,
    MeterData
):

    def __post_init__(self):
        self.dispatch_ts = pd.DataFrame(index=self.meter_ts.index)
        self.flexed_meter_ts = pd.DataFrame(index=self.meter_ts.index)

        Validator.data_cols(
            self.meter_ts,
            (
                'equivalent_thermal_energy',
                'electrical_energy',
                'gross_electrical_energy'
            )
        )
        self.meter_ts['other_electrical_energy'] = \
            self.meter_ts['gross_electrical_energy'] - self.meter_ts['electrical_energy']
        self.meter_ts['gross_mixed_electrical_thermal'] = \
            self.meter_ts['other_electrical_energy'] + self.meter_ts['equivalent_thermal_energy']

    def calculate_flexed_demand(
            self,
            name,
    ):
        self.meter_ts['equivalent_thermal_energy'] = updated_meter_data
        self.meter_ts['electrical_energy'] = \
            self.meter_ts['equivalent_thermal_energy'] / self.coefficient_of_performance
        self.meter_ts['gross_electrical_energy'] = \
            self.meter_ts['electrical_energy'] + self.meter_ts['other_electrical_energy']

    @classmethod
    def from_electrical_meter(
            cls,
            name,
            electrical_meter: ElectricityMeterData,
            load_column: str,
            coefficient_of_performance: Union[float, np.ndarray, pd.Series],
    ):
        if isinstance(coefficient_of_performance, float):
            meter_ts = pd.DataFrame(
                electrical_meter.meter_ts[load_column],
                columns=['electrical_energy']
            )
            meter_ts['equivalent_thermal_energy'] = \
                meter_ts['electrical_energy'] * coefficient_of_performance
            meter_ts['gross_electrical_energy'] = electrical_meter.meter_ts['demand_energy']
            return cls(
                name,
                meter_ts,
                electrical_meter.sample_rate,
                electrical_meter.units,
                electrical_meter.sub_load_cols,
                coefficient_of_performance
            )