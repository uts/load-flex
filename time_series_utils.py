from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Union, List, Tuple
from numbers import Number
import pandas as pd
import numpy as np
from datetime import timedelta, datetime
from typing import Type
from dataclasses import dataclass, field
import calendar

WEEKEND_DAYS = ['saturday', 'sunday']
ALL_DAYS = tuple([x.lower() for x in list(calendar.day_name)])
WEEKDAYS = tuple([x for x in ALL_DAYS if x not in WEEKEND_DAYS])


@dataclass
class EventOccurrence(ABC):
    @abstractmethod
    def is_due(self, dt: datetime):
        pass


@dataclass
class PeriodicEvents(EventOccurrence):
    start_dt: datetime
    period: timedelta
    next_periodic_event: datetime = field(init=False)

    def __post_init__(self):
        self.next_periodic_event = self.start_dt

    def is_due(self, dt):
        due = False
        if dt >= self.next_periodic_event:
            due = True
            self.next_periodic_event = dt + self.period
        return due


@dataclass
class SpecificEvents(EventOccurrence):
    events: Tuple[datetime]

    def is_due(self, dt):
        return dt in self.events


@dataclass
class SpecificHourEvents(EventOccurrence):
    hours: Tuple[int]
    monday: bool = False
    tuesday: bool = False
    wednesday: bool = False
    thursday: bool = False
    friday: bool = False
    saturday: bool = False
    sunday: bool = False

    all_days: bool = False
    weekends: bool = False
    weekdays: bool = False

    def __post_init__(self):
        if self.all_days:
            for day in ALL_DAYS:
                setattr(self, day, True)
        if self.weekends:
            for day in WEEKEND_DAYS:
                setattr(self, day, True)
        if self.weekdays:
            for day in WEEKDAYS:
                setattr(self, day, True)

    def is_due(self, dt: datetime):
        due = False
        weekday = dt.strftime('%A').lower()
        if getattr(self, weekday):
            if dt.hour in self.hours:
                if dt.minute == 0:
                    due = True
        return due


@dataclass
class Schedule:
    event_occurrences: List[EventOccurrence]

    def event_due(self, dt: datetime) -> bool:
        due = False
        for occurrence in self.event_occurrences:
            due = True if occurrence.is_due(dt) else due
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


@dataclass
class TOUShiftingCalculator:
    @staticmethod
    def cap_area(arr: np.ndarray):
        cap_arr = arr - arr.min()
        return cap_arr.sum()

    @staticmethod
    def cap_height(arr: np.ndarray):
        cap_arr = arr - arr.min()
        return cap_arr.max()

    @staticmethod
    def additional_depth(arr: np.ndarray, area_required: float):
        width = len(arr)
        return area_required / width

    @staticmethod
    def calculate_proposal(demand_arr: np.ndarray, area: float):
        cap_area = TOUShiftingCalculator.cap_area(demand_arr)
        additional_area_required = area - cap_area
        if additional_area_required > 0.0:
            additional_depth_required = TOUShiftingCalculator.additional_depth(
                demand_arr,
                additional_area_required
            )
            total_depth = \
                additional_depth_required + TOUShiftingCalculator.cap_height(demand_arr)
            proposal = demand_arr.max() - total_depth
        else:
            proposal = demand_arr.max() - TOUShiftingCalculator.cap_height(demand_arr)
        return proposal
