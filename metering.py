from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Union
from abc import ABC, abstractmethod

import pandas as pd
import numpy as np
from ts_tariffs.sites import Validator, MeterData, ElectricityMeterData


@dataclass
class ElectroFlexMeter(ElectricityMeterData):
    @abstractmethod
    def adjusted_meter_ts(
            self,
            name: str,
            updated_meter_data: np.ndarray
    ) -> ElectroFlexMeter:
        pass


@dataclass
class PowerFlexMeter(ElectroFlexMeter):
    """ ElectricityMeterData with capability to adjust power and apparent
    power based on change in energy demand

    Assumes energy units as kWh
    """

    def adjusted_meter_ts(
            self,
            name,
            updated_meter_data: np.ndarray
    ) -> PowerFlexMeter:
        """ Adjust power, apparent power profiles according to a
         change in demand energy
        """

        new_meter_ts = self.meter_ts.copy()
        new_meter_ts['demand_energy'] = updated_meter_data
        energy_diff = updated_meter_data - self.meter_ts['demand_energy']
        power_diff = energy_diff * self.sample_rate / timedelta(hours=1)
        new_meter_ts['demand_power'] += power_diff
        new_meter_ts['demand_apparent'] += power_diff / self.meter_ts['power_factor']

        return PowerFlexMeter(
            name,
            new_meter_ts,
            self.sample_rate,
            self.units,
            self.sub_load_cols
        )


@dataclass
class ThermalFlexMeter(ElectroFlexMeter):
    coefficient_of_performance: Union[float, np.ndarray]

    def __post_init__(self):
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

    def adjusted_meter_ts(
            self,
            name,
            updated_meter_data: np.ndarray
    ) -> ThermalFlexMeter:
        self.meter_ts['equivalent_thermal_energy'] = updated_meter_data
        self.meter_ts['electrical_energy'] = \
            self.meter_ts['equivalent_thermal_energy'] / self.coefficient_of_performance
        self.meter_ts['gross_electrical_energy'] = \
            self.meter_ts['electrical_energy'] + self.meter_ts['other_electrical_energy']
        return ThermalFlexMeter(
            self.name,
            self.meter_ts,
            self.sample_rate,
            self.units,
            self.sub_load_cols,
            self.coefficient_of_performance
        )

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
