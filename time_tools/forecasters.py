from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import timedelta, datetime

import pandas as pd


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