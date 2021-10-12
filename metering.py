from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta, datetime
from typing import Union, Dict
from abc import abstractmethod, ABC

import pandas as pd
import numpy as np
from ts_tariffs.sites import Validator, ElectricityMeterData, MeterData


class Converter:
    @staticmethod
    def energy_to_power(
            delta_energy: Union[float, np.ndarray, pd.Series, pd.DataFrame],
            delta_t_hours: float
    ) -> Union[float, np.ndarray, pd.Series, pd.DataFrame]:
        return delta_energy / delta_t_hours

    @staticmethod
    def power_to_apparent(
            power: Union[float, np.ndarray, pd.Series, pd.DataFrame],
            power_factor: Union[float, np.ndarray, pd.Series, pd.DataFrame]
    ) -> Union[float, np.ndarray, pd.Series, pd.DataFrame]:
        return power / power_factor

    @staticmethod
    def thermal_to_electrical(
            thermal: Union[float, np.ndarray, pd.Series, pd.DataFrame],
            coefficient_of_performance: Union[float, np.ndarray, pd.Series, pd.DataFrame]
    ) -> Union[float, np.ndarray, pd.Series, pd.DataFrame]:
        return thermal / coefficient_of_performance

    @staticmethod
    def electrical_to_thermal(
            electrical: Union[float, np.ndarray, pd.Series, pd.DataFrame],
            coefficient_of_performance: Union[float, np.ndarray, pd.Series, pd.DataFrame]
    ) -> Union[float, np.ndarray, pd.Series, pd.DataFrame]:
        return electrical * coefficient_of_performance


@dataclass
class DispatchFlexer(ABC):
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
class PowerFlexMeter(DispatchFlexer, ElectricityMeterData):
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
        df = self.meter_ts.copy()
        df['demand_energy'] += self.dispatch_ts[['charge', 'discharge']].sum(axis=1)
        df['demand_power'] = Converter.energy_to_power(
            df['demand_energy'],
            self.sample_rate / timedelta(hours=1)
        )
        df['demand_apparent'] = Converter.power_to_apparent(
            df['demand_power'],
            df['power_factor']
        )
        self.flexed_meter_ts = df


@dataclass
class ThermalLoadProperties:
    charge_as: str
    discharge_as: str
    flex_cop: Union[float, np.ndarray]
    load_cop: Union[float, np.ndarray]


@dataclass
class ThermalLoadFlexMeter(
    DispatchFlexer,
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

    def augment_load(
            self,
            augmentation,
            augment_as: str,
            coeff_of_performance: Union[float, np.ndarray]
    ):
        df = self.meter_ts.copy()
        if augment_as == 'thermal':
            df['equivalent_thermal_energy'] += augmentation
            augmentation = Converter.thermal_to_electrical(
                augmentation,
                coeff_of_performance
            )
        else:
            df['equivalent_thermal_energy'] += Converter.electrical_to_thermal(
                augmentation,
                coeff_of_performance
            )

        df['electrical_energy'] += augmentation
        df['gross_electrical_energy'] += augmentation
        self.flexed_meter_ts = df

    def calculate_flexed_demand(
            self,
            name,
    ):
        self.augment_load(
            self.dispatch_ts['charge'],
            self.charge_as,
            self.flex_cop
        )
        self.augment_load(
            self.dispatch_ts['discharge'],
            self.discharge_as,
            self.load_cop
        )

    @classmethod
    def from_electrical_meter(
            cls,
            name,
            electrical_meter: ElectricityMeterData,
            load_column: str,
            charge_as: str,
            discharge_as: str,
            flex_cop: Union[float, np.ndarray, pd.Series],
            load_cop: Union[float, np.ndarray, pd.Series],

    ):
        if isinstance(load_cop, float):
            meter_ts = pd.DataFrame(
                electrical_meter.meter_ts[load_column],
                columns=['electrical_energy']
            )
            meter_ts['equivalent_thermal_energy'] = \
                meter_ts['electrical_energy'] * load_cop
            meter_ts['gross_electrical_energy'] = electrical_meter.meter_ts['demand_energy']
            return cls(
                name,
                meter_ts,
                electrical_meter.sample_rate,
                electrical_meter.units,
                charge_as,
                discharge_as,
                flex_cop,
                load_cop
            )
