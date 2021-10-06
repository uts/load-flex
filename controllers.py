from dataclasses import dataclass
from abc import ABC, abstractmethod
from typing import Type, List, Union
from numbers import Number
import numpy as np
import pandas as pd
from ts_tariffs.sites import ElectricityMeterData

from metering import PowerFlexMeter, ThermalFlexMeter
from time_series_utils import Scheduler, Forecaster, PeakShaveTools
from equipment import Equipment, Storage
from storage import Battery


@dataclass
class Conditions(ABC):
    @abstractmethod
    def limit_dispatch(self) -> float:
        pass

    @abstractmethod
    def prevent_dispatch(self) -> bool:
        pass


@dataclass
class Controller(ABC):
    name: str
    equipment: Equipment = None
    forecaster: Forecaster = None
    forecast_scheduler: Scheduler = None
    conditions: List[Conditions] = None
    dispatch_report: pd.DataFrame = None
    demand: ElectricityMeterData = None
    peak_threshold: float = 0.0

    @abstractmethod
    def update_dispatch_report(self, update):
        pass

    @abstractmethod
    def dispatch(self):
        pass


@dataclass
class StorageController(Controller):
    equipment: Storage = None
    dispatch_on: str = None

    @abstractmethod
    def set_limit(
            self,
            demand_forecast: Union[List[Number], np.ndarray, pd.Series],
            area: float
    ):
        pass

    def dispatch_proposal(self, demand: float) -> float:
        proposal = self.peak_threshold - demand
        return proposal

    def dispatch(self):
        # Initialise limits
        self.set_limit(
            self.forecaster.look_ahead(
                self.demand.meter_ts,
                self.demand.meter_ts.first_valid_index()
            ),
            self.equipment.available_energy
        )
        for dt, demand in self.demand.meter_ts.iteritems():
            if self.forecast_scheduler.event_due(dt):
                self.set_limit(
                    self.forecaster.look_ahead(
                        self.demand.meter_ts[self.dispatch_on],
                        dt
                    ),
                    self.equipment.available_energy
                )
            dispatch = self.equipment.energy_request(
                self.dispatch_proposal(demand[self.dispatch_on])
            )
            self.update_dispatch_report({
                'datetime': dt,
                self.dispatch_on: demand,
                f'{self.equipment.name}_charged': max(dispatch, 0),
                f'{self.equipment.name}_discharged': min(dispatch, 0),
                'new_net_demand': demand + dispatch,
                'peak_threshold': self.peak_threshold,
                **self.equipment.status()
            })
        self.dispatch_report.set_index('datetime', inplace=True)

    def update_dispatch_report(self, update: dict):
        if not isinstance(self.dispatch_report, pd.DataFrame):
            self.dispatch_report = pd.DataFrame()
        self.dispatch_report = self.dispatch_report.append(update, ignore_index=True)


@dataclass
class SimpleBatteryController(StorageController):
    def set_limit(
            self,
            demand_forecast: Union[List[Number], np.ndarray, pd.Series],
            area: float
    ):
        sorted_arr = np.sort(
            self.demand.meter_ts[self.dispatch_on].values
        )
        peak_areas = PeakShaveTools.cumulative_peak_areas(sorted_arr)
        index = PeakShaveTools.peak_area_idx(peak_areas, area)
        proposed_limit = np.flip(sorted_arr)[index]
        self.peak_threshold = max(self.peak_threshold, proposed_limit)


@dataclass
class ThermalStorageController(StorageController):
    demand: ThermalFlexMeter = None
    dispatch_on: str = 'equivalent_thermal_energy'

    def set_limit(
            self,
            demand_arr: Union[List[Number], np.ndarray, pd.Series],
            area: float
    ):
        ts = self.demand.meter_ts.copy()
        ts.sort_values('gross_electrical_energy', inplace=True)
        ts.reset_index(inplace=True, drop=True)

        limiting_threshold_idx = ts['other_electrical_energy'].idxmax()
        proposed_limit = PeakShaveTools.sub_load_peak_shave_limit(
            ts,
            limiting_threshold_idx,
            area,
            'gross_mixed_electrical_thermal',
            'equivalent_thermal_energy'
        )
        self.peak_threshold = max(self.peak_threshold, proposed_limit)