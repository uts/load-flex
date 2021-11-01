from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta, datetime
from typing import Union, Dict, List
from abc import abstractmethod

import pandas as pd
import numpy as np
from ts_tariffs.sites import MeterData, MeterPlotConfig

from equipment import Dispatch

POWER_METER_COLS = (
    'demand_energy',
    'demand_power',
    'generation_energy',
    'power_factor',
    'demand_apparent'
)

THERMAL_METER_COLS = (
    *POWER_METER_COLS,
    'subload_energy'
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

    @staticmethod
    def power_meter_from_energy(
        energy_series: pd.Series,
        power_factor_series: pd.Series,
        sample_rate: timedelta
    ):
        energy_series.rename('demand_energy', inplace=True)
        df = pd.DataFrame(energy_series)
        df['demand_power'] = Converter.energy_to_power(
            df['demand_energy'],
            sample_rate / timedelta(hours=1)
        )
        df['demand_apparent'] = Converter.power_to_apparent(
            df['demand_power'],
            power_factor_series
        )
        return df



@dataclass
class DispatchFlexMeter(MeterData):
    name: str
    flexed_tseries: pd.DataFrame = field(init=False)

    @abstractmethod
    def calculate_flexed_tseries(
            self,
            name: str,
            return_new_meter: bool = False,
    ):
        pass

    @abstractmethod
    def update_dispatch(
            self,
            dt: datetime,
            dispatch: Dispatch,
            dispatch_on: str,
            other: Dict[str, Union[float, str]] = None,
    ):
        pass


@dataclass
class PowerFlexMeter(DispatchFlexMeter):
    dispatch_tseries: pd.DataFrame = field(init=False)

    def __post_init__(self):
        Validator.data_cols(self.tseries, POWER_METER_COLS)
        self.dispatch_tseries = pd.DataFrame(index=self.tseries.index)
        self.flexed_tseries = pd.DataFrame(index=self.tseries.index)

    def update_dispatch(
            self,
            dt: datetime,
            dispatch: Dispatch,
            dispatch_on: str,
            other: Dict[str, Union[float, str]] = None,
            return_net=False
    ):
        self.dispatch_tseries.loc[dt, 'charge'] = dispatch.charge
        self.dispatch_tseries.loc[dt, 'discharge'] = dispatch.discharge
        x = self.tseries.loc[dt, dispatch_on]
        flexed_net = self.tseries.loc[dt, dispatch_on] - dispatch.net_value
        self.dispatch_tseries.loc[dt, 'flexed_net_energy'] = flexed_net
        if other:
            for key, value in other.items():
                self.dispatch_tseries.loc[dt, key] = value

    def calculate_flexed_tseries(
            self,
            name,
            return_new_meter: bool = False,
    ):
        """ Adjust power, apparent power profiles according to a
         change in demand energy
        """
        self.flexed_tseries = Converter.power_meter_from_energy(
            self.dispatch_tseries['flexed_net_energy'],
            self.tseries['power_factor'],
            self.sample_rate
        )
        self.flexed_tseries['generation_energy'] = self.tseries['generation_energy']
        self.flexed_tseries['power_factor'] = self.tseries['power_factor']

        if return_new_meter:
            column_map = {
                column: {
                    'ts': column,
                    'units': self.units[column]
                }
                for column in POWER_METER_COLS
            }
            return PowerFlexMeter.from_dataframe(
                name,
                self.flexed_tseries,
                self.sample_rate,
                column_map,
                self.plot_configs
            )


@dataclass
class ThermalLoadProperties:
    flex_cop: Union[float, np.ndarray]
    load_cop: Union[float, np.ndarray]


@dataclass
class ThermalLoadFlexMeter(DispatchFlexMeter):
    thermal_properties: ThermalLoadProperties
    thermal_tseries: pd.DataFrame = field(init=False)
    thermal_dispatch_tseries: pd.DataFrame = field(init=False)
    electrical_dispatch_tseries: pd.DataFrame = field(init=False)
    flexed_tseries: pd.DataFrame = field(init=False)

    def __post_init__(self):
        Validator.data_cols(
            self.tseries,
            THERMAL_METER_COLS
        )
        self.tseries['balance_energy'] = \
            self.tseries['demand_energy'] - self.tseries['subload_energy']
        self.create_thermal_tseries()
        self.thermal_dispatch_tseries = pd.DataFrame(index=self.tseries.index)
        self.electrical_dispatch_tseries = pd.DataFrame(index=self.tseries.index)
        self.flexed_tseries = pd.DataFrame(index=self.tseries.index)

    def create_thermal_tseries(self):
        self.thermal_tseries = pd.DataFrame(index=self.tseries.index)
        self.thermal_tseries['load_cop'] = self.thermal_properties.load_cop
        self.thermal_tseries['flex_cop'] = self.thermal_properties.flex_cop
        self.thermal_tseries['subload_energy'] =\
            self.tseries['subload_energy'] * self.thermal_tseries['load_cop']

    def update_dispatch(
            self,
            dt: datetime,
            dispatch: Dispatch,
            dispatch_on: str,
            other: Dict[str, Union[float, str]] = None,
    ):
        self.thermal_dispatch_tseries.loc[dt, 'charge'] = dispatch.charge
        self.thermal_dispatch_tseries.loc[dt, 'discharge'] = dispatch.discharge
        self.electrical_dispatch_tseries.loc[dt, 'charge'] = Converter.thermal_to_electrical(
                self.thermal_dispatch_tseries.loc[dt, 'charge'],
                self.thermal_tseries.loc[dt, 'flex_cop']
            )
        self.electrical_dispatch_tseries.loc[dt, 'discharge'] = Converter.thermal_to_electrical(
                self.thermal_dispatch_tseries.loc[dt, 'discharge'],
                self.thermal_tseries.loc[dt, 'load_cop']
            )
        self.electrical_dispatch_tseries.loc[dt, 'energy_net'] = \
            self.electrical_dispatch_tseries.loc[dt, 'discharge'] \
            - self.electrical_dispatch_tseries.loc[dt, 'charge'] \

        if other:
            for key, value in other.items():
                self.thermal_dispatch_tseries.loc[dt, key] = value

    def calculate_flexed_tseries(
            self,
            name,
            return_new_meter: bool = False,
    ):
        self.flexed_tseries = Converter.power_meter_from_energy(
            self.tseries['demand_energy'] - self.electrical_dispatch_tseries['energy_net'],
            self.tseries['power_factor'],
            self.sample_rate
        )
        self.flexed_tseries['generation_energy'] = self.tseries['generation_energy']
        self.flexed_tseries['power_factor'] = self.tseries['power_factor']
        self.flexed_tseries['subload_energy'] =\
            self.tseries['subload_energy'] - self.electrical_dispatch_tseries['energy_net']

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
                self.flexed_tseries,
                self.sample_rate,
                column_map,
                self.plot_configs,
                self.thermal_properties
            )

    @classmethod
    def from_dataframe(
            cls,
            name: str,
            df: pd.DataFrame,
            sample_rate: timedelta,
            column_map: dict,
            plot_configs: Union[None, List[MeterPlotConfig]],
            thermal_properties: ThermalLoadProperties
    ):
        units = {}
        # Create cols according to column_map and cherry pick them for
        # instantiation of class object
        for meter_col, data in column_map.items():
            df[meter_col] = df[data['ts']]
            units[meter_col] = data['units']
        return cls(name, df[column_map.keys()], sample_rate, units, plot_configs, thermal_properties)

    @classmethod
    def from_powerflex_meter(
            cls,
            name: str,
            electrical_meter: PowerFlexMeter,
            thermal_properties: ThermalLoadProperties
    ):
        return cls(
            name,
            electrical_meter.tseries,
            electrical_meter.sample_rate,
            electrical_meter.units,
            electrical_meter.plot_configs,
            thermal_properties
        )