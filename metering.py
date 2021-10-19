from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta, datetime
from typing import Union, Dict
from abc import abstractmethod

import pandas as pd
import numpy as np
from ts_tariffs.sites import MeterData

ELECTRICITY_METER_COLS = (
    'demand_energy',
    'demand_power',
    'generation_energy',
    'power_factor',
    'demand_apparent'
)

THERMAL_METER_COLS = (
    'equivalent_thermal_energy',
    'electrical_energy',
    'gross_electrical_energy'
)


class Validator:
    @staticmethod
    def type_check(name, obj,valid_types: tuple):
        if not isinstance(obj, valid_types):
            valid_types_str = ', '.join(valid_types)
            raise TypeError(f'{name} must be type/s: {valid_types_str}')

    @staticmethod
    def data_cols(df, mandatory_cols: tuple):
        not_present = list([col not in df.columns for col in mandatory_cols])
        if any(not_present):
            content = ', '.join(np.array(mandatory_cols)[not_present])
            raise ValueError(f'The following columns must be present in dataframe: {content}')


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
class DispatchFlexMeter(MeterData):
    name: str
    dispatch_ts: pd.DataFrame = field(init=False)
    flexed_meter_ts: pd.DataFrame = field(init=False)

    @abstractmethod
    def calculate_flexed_demand(
            self,
            name: str,
            return_new_meter: bool = False,
    ):
        pass

    def update_dispatch(
            self,
            dt: datetime,
            charge: float,
            discharge: float,
            other: Dict[str, float] = None
    ):
        self.dispatch_ts.loc[dt, 'charge'] = charge
        self.dispatch_ts.loc[dt, 'discharge'] = discharge
        if other:
            for key, value in other.items():
                self.dispatch_ts.loc[dt, key] = value


@dataclass
class PowerFlexMeter(DispatchFlexMeter):

    def __post_init__(self):
        Validator.data_cols(self.tseries, ELECTRICITY_METER_COLS)
        self.dispatch_ts = pd.DataFrame(index=self.tseries.index)
        self.flexed_meter_ts = pd.DataFrame(index=self.tseries.index)

    def calculate_flexed_demand(
            self,
            name,
            return_new_meter: bool = False,
    ):
        """ Adjust power, apparent power profiles according to a
         change in demand energy
        """
        df = self.tseries.copy()
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
        if return_new_meter:
            column_map = {
                column: {
                    'ts': column,
                    'units': self.units[column]
                }
                for column in ELECTRICITY_METER_COLS
            }
            return PowerFlexMeter.from_dataframe(
                name,
                self.flexed_meter_ts,
                self.sample_rate,
                column_map
            )


@dataclass
class ThermalLoadProperties:
    charge_as: str
    discharge_as: str
    flex_cop: Union[float, np.ndarray]
    load_cop: Union[float, np.ndarray]


@dataclass
class ThermalLoadFlexMeter(
    DispatchFlexMeter,
):
    thermal_properties: ThermalLoadProperties

    def __post_init__(self):
        Validator.data_cols(
            self.tseries,
            THERMAL_METER_COLS
        )
        self.tseries['other_electrical_energy'] = \
            self.tseries['gross_electrical_energy'] - \
            self.tseries['electrical_energy']
        self.dispatch_ts = pd.DataFrame(index=self.tseries.index)
        self.flexed_meter_ts = pd.DataFrame(index=self.tseries.index)

    def augment_load(
            self,
            augmentation,
            augment_as: str,
            coeff_of_performance: Union[float, np.ndarray]
    ):
        df = self.tseries.copy()
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
            return_new_meter: bool = False,
    ):
        self.augment_load(
            self.dispatch_ts['charge'],
            self.thermal_properties.charge_as,
            self.thermal_properties.flex_cop
        )
        self.augment_load(
            self.dispatch_ts['discharge'],
            self.thermal_properties.discharge_as,
            self.thermal_properties.load_cop
        )
        if return_new_meter:
            column_map = {
                column: {
                    'ts': column,
                    'units': self.units[column]
                }
                for column in THERMAL_METER_COLS
            }
            return ThermalLoadFlexMeter.from_dataframe(
                name,
                self.flexed_meter_ts,
                self.sample_rate,
                column_map
            )

    @classmethod
    def from_powerflex_meter(
            cls,
            name,
            electrical_meter: PowerFlexMeter,
            load_column: str,
            thermal_properties: ThermalLoadProperties
    ):
        tseries = pd.DataFrame(
            electrical_meter.tseries[load_column],
            columns=['electrical_energy']
        )
        tseries['equivalent_thermal_energy'] = Converter.electrical_to_thermal(
            tseries['electrical_energy'],
            thermal_properties.load_cop
        )
        tseries['gross_electrical_energy'] = electrical_meter.tseries['demand_energy']
        return cls(
            name,
            tseries,
            electrical_meter.sample_rate,
            electrical_meter.units,
            thermal_properties
        )
