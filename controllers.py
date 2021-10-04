from abc import ABC, abstractmethod
from typing import Type, List, Union
from numbers import Number
import numpy as np
import pandas as pd

from time_series_utils import Scheduler, Forecaster, PeakShave
from equipment import Equipment, Storage, Battery


class Conditions(ABC):
    @abstractmethod
    def limit_dispatch(self) -> float:
        pass

    @abstractmethod
    def prevent_dispatch(self) -> bool:
        pass


class Controller(ABC):
    conditions: List[Conditions] = None
    dispatch_report: pd.DataFrame = None
    remaining_demand_arr: pd.Series = None
    peak_threshold: float = 0.0

    @abstractmethod
    def update_dispatch_report(self, update):
        pass

    @abstractmethod
    def dispatch(
            self,
            demand_arr: Union[List[Number], np.ndarray, pd.Series],
            forecaster: Type[Forecaster],
            equipment: Type[Equipment],
            scheduler: Type[Scheduler]
    ):
        pass


class SimpleBatteryController(Controller):
    def set_limit(
            self,
            demand_arr: Union[List[Number], np.ndarray, pd.Series],
            area: float
    ):
        sorted_arr = np.sort(demand_arr)
        peak_areas = PeakShave.cumulative_peak_areas(sorted_arr)
        index = PeakShave.peak_area_idx(peak_areas, area)
        proposed_limit = np.flip(sorted_arr)[index]
        self.peak_threshold = max(self.peak_threshold, proposed_limit)

    def dispatch_proposal(self, demand: float) -> float:
        proposal = self.peak_threshold - demand
        return proposal

    def update_dispatch_report(self, update: dict):
        if not isinstance(self.dispatch_report, pd.DataFrame):
            self.dispatch_report = pd.DataFrame()
        self.dispatch_report = self.dispatch_report.append(update, ignore_index=True)

    def dispatch(
            self,
            demand_arr: Union[List[Number], np.ndarray, pd.Series],
            forecaster: Type[Forecaster],
            battery: Type[Storage],
            forecast_scheduler: Type[Scheduler]
    ):
        # Initialise limits
        self.set_limit(
            forecaster.look_ahead(
                demand_arr,
                demand_arr.first_valid_index()
            ),
            battery.available_energy
        )
        for dt, demand in demand_arr.iteritems():
            if forecast_scheduler.event_due(dt):
                self.set_limit(
                    forecaster.look_ahead(demand_arr, dt),
                    battery.available_energy
                )
            battery_dispatch = battery.energy_request(self.dispatch_proposal(demand))
            self.update_dispatch_report({
                'datetime': dt,
                'demand': demand,
                'battery_charge': max(battery_dispatch, 0),
                'battery_discharge': min(battery_dispatch, 0),
                'net_demand': demand + battery_dispatch,
                'battery_soc': battery.state_of_charge,
                'peak_threshold': self.peak_threshold
            })
        print(self.dispatch_report.index.dtype)
        self.dispatch_report.set_index('datetime', inplace=True)