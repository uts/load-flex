from abc import ABC, abstractmethod
from typing import Type, List, Union
from numbers import Number
import numpy as np
import pandas as pd
from datetime import timedelta

from time_series_utils import Scheduler, Forecaster, PeakShave
from equipment import Equipment, Storage, Battery


class Controller(ABC):
    dispatch_report: pd.DataFrame = None,
    remaining_demand_arr: pd.Series = None

    @abstractmethod
    def update_dispatch_report(self):
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
    @staticmethod
    def set_limits(
            self,
            demand_arr: Union[List[Number], np.ndarray, pd.Series],
            area: float
    ):
        sorted_arr = np.sort(demand_arr)
        peak_areas = PeakShave.cumulative_peak_areas(sorted_arr)
        index = PeakShave.peak_area_idx(peak_areas, area)
        self.charge_limit = np.flip(sorted_arr)[index]
        self.discharge_limit = max(sorted_arr) - np.flip(sorted_arr)[index]

    def update_dispatch_report(self):
        pass

    def dispatch(
            self,
            demand_arr: Union[List[Number], np.ndarray, pd.Series],
            forecaster: Type[Forecaster],
            battery: Type[Storage],
            check_limits_schedule: Type[Scheduler]
    ):
        forecast_window = forecaster.look_ahead(demand_arr, demand_arr.first_valid_index())
        self.set_limits(forecast_window, Battery.available_energy)
        for dt, demand in demand_arr.iteritems():
            if check_limits_schedule.event_due(dt):
                forecast_window = forecaster.look_ahead(demand_arr, dt)
                self.set_limits(forecast_window, Battery.available_energy)
                ###