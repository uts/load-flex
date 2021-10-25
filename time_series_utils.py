from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Union, List
from numbers import Number
import pandas as pd
import numpy as np
from datetime import timedelta, datetime
from typing import Type
from dataclasses import dataclass


@dataclass
class Scheduler:
    start_dt: datetime
    interval: timedelta

    def __post_init__(self):
        self.next_event_due = self.start_dt

    def event_due(self, dt: datetime) -> bool:
        due = False
        if dt >= self.next_event_due:
            due = True
            self.next_event_due = dt + self.interval
        return due


@dataclass
class Forecaster(ABC):
    window: timedelta

    @abstractmethod
    def look_ahead(
        self,
        time_series: pd.DataFrame,
        start_datetime: datetime,
    ) -> pd.DataFrame:
        pass


@dataclass
class PerfectForcaster(Forecaster):
    def look_ahead(
        self,
        time_series: pd.DataFrame,
        start_datetime: datetime,
    ):
        fmt = '%Y-%m-%d %H:%M'
        end_time = start_datetime + self.window
        return time_series[start_datetime.strftime(fmt): end_time.strftime(fmt)]


@dataclass
class PeakShaveTools:
    @staticmethod
    def cumulative_peak_areas(sorted_arr: np.ndarray):
        delta_energy = np.append(np.diff(sorted_arr), 0)
        reverse_index = np.array(range(len(sorted_arr) - 1, -1, -1))
        delta_area = delta_energy * reverse_index
        return np.cumsum(np.flip(delta_area))

    @staticmethod
    def peak_area_idx(peak_areas, area, max_idx=None):
        idx = np.searchsorted(peak_areas, area) - 1
        if max_idx:
            return min(idx, max_idx)
        else:
            return idx

    @staticmethod
    def sub_load_peak_shave_limit(
            sorted_df: pd.DataFrame,
            max_idx: int,
            area: float,
            gross_col: str,
            sub_col: str,
    ) -> float:
        for i, row in sorted_df.iloc[:max_idx:-1].iterrows():
            exposed_gross = sorted_df[gross_col].values - row[gross_col]
            exposed_gross = np.where(exposed_gross < 0, 0, exposed_gross)
            exposed_sub = np.clip(sorted_df[sub_col].values, 0, exposed_gross)
            exposed_sub_area = sum(exposed_sub)
            if exposed_sub_area >= area:
                return sorted_df[gross_col].iloc[i + 1]
        return 0.0
