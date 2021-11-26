from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta, datetime
from typing import Union, Dict, List
from abc import abstractmethod

import pandas as pd
import numpy as np
from ts_tariffs.sites import MeterData, MeterPlotConfig

from equipment.equipment import Dispatch
from validators import Validator

POWER_METER_COLS = (
    'demand_energy',
    'demand_power',
    'generation_energy',
    'power_factor',
    'demand_apparent',
)

THERMAL_METER_COLS = (
    *POWER_METER_COLS,
    'subload_energy',
)


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
    def power_meter_tseries_from_energy(
            energy_series: pd.Series,
            power_factor_series: pd.Series,
            sample_rate: timedelta,
            subload_series: pd.Series = None
    ) -> pd.DataFrame:
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
        df['power_factor'] = power_factor_series

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
            other: Dict[str, Union[float, str]] = None,
    ):
        pass

    @abstractmethod
    def consolidate_updates(self, dispatch_on: str):
        pass

    @abstractmethod
    def reset_meter(self):
        pass


@dataclass
class PowerFlexMeter(DispatchFlexMeter):
    dispatch_tseries: pd.DataFrame = field(init=False)

    _updater_arrays: dict = field(init=False)
    _reportables: List[str] = field(init=False)

    def __post_init__(self):
        Validator.data_cols(self.tseries, POWER_METER_COLS)
        if 'subload_energy' not in self.tseries.columns:
            self.tseries['subload_energy'] = 0.0
        self.tseries['balance_energy'] = \
            self.tseries['demand_energy'] - self.tseries['subload_energy']
        self.dispatch_tseries = pd.DataFrame(index=self.tseries.index)
        self.flexed_tseries = pd.DataFrame(index=self.tseries.index)

        self._updater_arrays = {
            'dt': [],
            'charge': [],
            'discharge': [],
            'net': []
        }
        self._reportables = []

    def scale_meter_data(self, factor: float, exclude_cols: List[str] = None):
        """ Multiply all .tseries cols by a common factor
        """
        scale_cols = [col for col in self.tseries if col not in exclude_cols]
        for col in scale_cols:
            self.tseries[col] *= factor


    def set_reportables(self, reportables: List[str]):
        self._reportables = reportables
        for reportable in self._reportables:
            self._updater_arrays[reportable] = []

    def update_dispatch(
            self,
            dt: datetime,
            dispatch: Dispatch,
            other: Dict[str, Union[float, str]] = None,
    ):
        self._updater_arrays['charge'].append(dispatch.charge)
        self._updater_arrays['discharge'].append(dispatch.discharge)
        self._updater_arrays['net'].append(dispatch.net_value)
        if other:
            for key, value in other.items():
                self._updater_arrays[key].append(value)

    def consolidate_updates(self, dispatch_on: str):
        self.dispatch_tseries['charge'] = self._updater_arrays['charge']
        self.dispatch_tseries['discharge'] = self._updater_arrays['discharge']
        self.dispatch_tseries['net'] = self._updater_arrays['net']
        self.dispatch_tseries['flexed_net_energy'] = \
            self.tseries[dispatch_on] - self.dispatch_tseries['net']

        if self._reportables:
            for key in self._reportables:
                self.dispatch_tseries[key] = self._updater_arrays[key]

    def calculate_flexed_tseries(
            self,
            name,
            return_new_meter: bool = False,
    ):
        """ Adjust power, apparent power profiles according to a
         change in demand energy
        """

        self.flexed_tseries = Converter.power_meter_tseries_from_energy(
            self.dispatch_tseries['flexed_net_energy'],
            self.tseries['power_factor'],
            self.sample_rate
        )
        self.flexed_tseries['generation_energy'] = self.tseries['generation_energy']

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

    def reset_meter(self):
        self.__post_init__()


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

    _updater_arrays: dict = field(init=False)
    _reportables: List[str] = field(init=False)

    def __post_init__(self):
        Validator.data_cols(
            self.tseries,
            THERMAL_METER_COLS
        )
        self.tseries['balance_energy'] = \
            self.tseries['demand_energy'] - self.tseries['subload_energy']
        self.create_thermal_tseries()
        self.tseries['gross_mixed_electrical_and_thermal'] = \
            self.thermal_tseries['gross_mixed_electrical_and_thermal']
        self.thermal_dispatch_tseries = pd.DataFrame()
        self.electrical_dispatch_tseries = pd.DataFrame()
        self.flexed_tseries = pd.DataFrame(index=self.tseries.index)

        self._updater_arrays = {
            'dt': [],
            'thermal_dispatch_tseries_charge': [],
            'thermal_dispatch_tseries_discharge': [],
            'electrical_dispatch_tseries_charge': [],
            'electrical_dispatch_tseries_discharge': [],
            'electrical_dispatch_tseries_energy_net': [],
        }

    def set_reportables(self, reportables: List[str]):
        self._reportables = reportables
        for reportable in self._reportables:
            self._updater_arrays[reportable] = []

    def create_thermal_tseries(self):
        self.thermal_tseries = pd.DataFrame(index=self.tseries.index)
        self.thermal_tseries['load_cop'] = self.thermal_properties.load_cop
        self.thermal_tseries['flex_cop'] = self.thermal_properties.flex_cop
        self.thermal_tseries['subload_energy'] =\
            self.tseries['subload_energy'] * self.thermal_tseries['load_cop']
        self.thermal_tseries['gross_mixed_electrical_and_thermal'] = \
            self.thermal_tseries['subload_energy'] + self.tseries['balance_energy']

    def update_dispatch(
            self,
            dt: datetime,
            dispatch: Dispatch,
            other: Dict[str, Union[float, str]] = None,
    ):
        self._updater_arrays['dt'].append(dt)
        self._updater_arrays['thermal_dispatch_tseries_charge'].append(dispatch.charge)
        self._updater_arrays['thermal_dispatch_tseries_discharge'].append(dispatch.discharge)

        if other:
            for key, value in other.items():
                self._updater_arrays[key].append(value)

    def consolidate_updates(self, dispatch_on: str):
        self.thermal_dispatch_tseries.index = self._updater_arrays['dt']
        self.thermal_dispatch_tseries['charge'] = self._updater_arrays['thermal_dispatch_tseries_charge']
        self.thermal_dispatch_tseries['discharge'] = self._updater_arrays['thermal_dispatch_tseries_discharge']

        for key in self._reportables:
            self.thermal_dispatch_tseries[key] = self._updater_arrays[key]

        self.electrical_dispatch_tseries['charge'] = Converter.thermal_to_electrical(
            self.thermal_dispatch_tseries['charge'],
            self.thermal_tseries['flex_cop']
        )
        self.electrical_dispatch_tseries['discharge'] = Converter.thermal_to_electrical(
            self.thermal_dispatch_tseries['discharge'],
            self.thermal_tseries['load_cop']
        )
        self.electrical_dispatch_tseries['energy_net'] = \
            self.electrical_dispatch_tseries['discharge'] \
            - self.electrical_dispatch_tseries['charge']

    def calculate_flexed_tseries(
            self,
            name,
            return_new_meter: bool = False,
    ):
        self.flexed_tseries = Converter.power_meter_tseries_from_energy(
            self.tseries['demand_energy'] - self.electrical_dispatch_tseries['energy_net'],
            self.tseries['power_factor'],
            self.sample_rate
        )
        self.flexed_tseries['generation_energy'] = self.tseries['generation_energy']
        self.flexed_tseries['power_factor'] = self.tseries['power_factor']
        self.flexed_tseries['subload_energy'] =\
            self.tseries['subload_energy'] - self.electrical_dispatch_tseries['energy_net']
        self.flexed_tseries['gross_mixed_electrical_and_thermal'] = \
            self.thermal_tseries['gross_mixed_electrical_and_thermal'] + \
            + self.thermal_dispatch_tseries['charge'] \
            - self.thermal_dispatch_tseries['discharge']

        if return_new_meter:
            column_map = {
                column: {
                    'ts': column,
                    'units': self.units[column]
                }
                for column in THERMAL_METER_COLS
            }
            column_map.update({
                'gross_mixed_electrical_and_thermal': {
                    'ts': 'gross_mixed_electrical_and_thermal',
                    'units': 'mixed'
                }
            })
            return ThermalLoadFlexMeter.from_dataframe(
                name,
                self.flexed_tseries,
                self.sample_rate,
                column_map,
                self.plot_configs,
                self.thermal_properties
            )

    def reset_meter(self):
        self.__post_init__()

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