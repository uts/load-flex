from abc import ABC, abstractmethod
from typing import List, Tuple
import pandas as pd
from datetime import timedelta, datetime
from dataclasses import dataclass, field
import calendar

WEEKEND_DAYS = ['saturday', 'sunday']
ALL_DAYS = tuple([x.lower() for x in list(calendar.day_name)])
WEEKDAYS = tuple([x for x in ALL_DAYS if x not in WEEKEND_DAYS])


@dataclass
class DailyHours(ABC):
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

    @staticmethod
    def day_str(dt):
        return dt.strftime('%A').lower()

    def relevant_day(self, dt):
        return getattr(self, self.day_str(dt))


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
class SpecificHourEvents(EventOccurrence, DailyHours):
    def is_due(self, dt: datetime):
        due = False
        if self.relevant_day(dt):
            if dt.hour in self.hours:
                if dt.minute == 0:
                    due = True
        return due


@dataclass
class EventSchedule:
    event_occurrences: List[EventOccurrence]
    always_due: bool = False

    def add_event(self, event: EventOccurrence):
        self.event_occurrences.append(event)

    def event_due(self, dt: datetime) -> bool:
        if self.always_due:
            due = True
        else:
            due = False
            for occurrence in self.event_occurrences:
                due = True if occurrence.is_due(dt) else due
        return due


@dataclass
class Period(ABC):
    @abstractmethod
    def period_active(self, dt: datetime):
        pass


@dataclass
class DailyPeriod(Period, DailyHours):
    def period_active(self, dt: datetime):
        active = False
        if self.relevant_day(dt):
            if dt.hour in self.hours:
                active = True
        return active


@dataclass
class PeriodSchedule:
    periods: List[Period] = None
    always_active: bool = False

    def __post_init__(self):
        if not self.periods:
            self.periods = []

    def period_active(self, dt: datetime) -> bool:
        if self.always_active:
            active = True
        else:
            active = False
            for period in self.periods:
                active = True if period.period_active(dt) else active
        return active


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
