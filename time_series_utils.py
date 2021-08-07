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
class Scheduler(ABC, BaseModel):
    start_dt: datetime
    interval: timedelta
    initialised = False
    next_event_due: datetime = None

    def __post_init__(self):
        self.next_event_due = self.start_dt

    def event_due(self, dt: datetime) -> bool:
        due = False
        if dt > self.next_event_due:
            due = True
            self.next_event_due = dt + self.interval
        return due


class Forecaster(ABC):
    window: timedelta

    @abstractmethod
    def look_ahead(
        self,
        arr: pd.Series,
        start_datetime: datetime,
    ) -> np.ndarray:
        pass


class PerfectForcaster(Forecaster):
    def look_ahead(
        self,
        arr: pd.Series,
        start_datetime: datetime,
    ):
        fmt = '%Y-%m-%d HH:MM'
        end_time = start_datetime + self.foresight
        return arr[start_datetime.strftime(fmt): end_time.strftime(fmt)]


class PeakShave:
    @staticmethod
    def cumulative_peak_areas(sorted_arr):
        delta_energy = np.diff(sorted_arr)
        reverse_index = np.array(range(len(sorted_arr), 1, -1))
        delta_area = delta_energy * reverse_index
        return np.cumsum(np.flip(delta_area))

    @staticmethod
    def peak_area_idx(peak_areas, area):
        return np.searchsorted(peak_areas, area)
