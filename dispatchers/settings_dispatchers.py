from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Union

import pandas as pd

from equipment.equipment import Dispatch
from equipment.settings_adjustments import CompressorSuctionPressure, FanThrottle, Setting
from time_series_tools.metering import DispatchFlexMeter
from time_series_tools.schedulers import PeriodSchedule, EventSchedule, DateRangePeriod
from time_series_tools.wholesale_prices import MarketPrices


@dataclass
class RepaySlot:
    from_time: str
    to_time: str


@dataclass
class SettingsDispatcher(ABC):
    name: str
    meter: DispatchFlexMeter
    setter_schedule: EventSchedule
    market_prices: Union[MarketPrices, None]
    dispatch_on: str
    setting: Setting = field(default=None)
    dispatch_schedule: PeriodSchedule = field(default=None)
    repay_schedule: PeriodSchedule = field(default=None)
    forecast_resolution: timedelta = field(default=timedelta(hours=0.5))
    repay_slot: RepaySlot = None

    def __post_init__(self):
        if not self.dispatch_schedule:
            self.dispatch_schedule = PeriodSchedule([])
        if not self.repay_schedule:
            self.repay_schedule = PeriodSchedule([])

    @abstractmethod
    def schedule_market_optimised_dispatch(
            self,
            dt: datetime,
    ):
        pass

    @abstractmethod
    def schedule_retail_optimised_dispatch(
            self,
            dt: datetime,
    ):
        pass

    def define_repay_period(self, price_forecast: pd.DataFrame) -> pd.DataFrame:
        if self.repay_slot:
            return price_forecast.between_time(
                self.repay_slot.from_time,
                self.repay_slot.to_time
            )
        else:
            return price_forecast

    def dispatch(self):
        for dt, demand in self.meter.tseries.iterrows():
            if self.setter_schedule.event_due(dt):
                if self.market_prices:
                    self.schedule_market_optimised_dispatch(dt)
            if self.dispatch_schedule.period_active(dt):
                dispatch = self.setting.apply_setting(demand[self.dispatch_on])
            else:
                dispatch = Dispatch.from_raw_float(0.0)
            if self.repay_schedule.period_active(dt):
                dispatch = self.setting.repay_dispatch(demand[self.dispatch_on])
            self.commit_dispatch(dt, dispatch, demand[self.dispatch_on])

        self.meter.consolidate_updates(self.dispatch_on)

    def report_dispatch(self, dt: datetime, dispatch: Dispatch):
        dispatch.validate()
        self.meter.update_dispatch_at_t(
            dt,
            dispatch,
        )

    def commit_dispatch(self, dt: datetime, dispatch: Dispatch, demand: float):
        self.report_dispatch(dt, dispatch)


@dataclass
class CompressorSuctionPressureDispatcher(SettingsDispatcher):
    setting: CompressorSuctionPressure = field(default=None)

    def schedule_market_optimised_dispatch(
            self,
            dt: datetime,
    ):
        price_forecast = self.market_prices.forecast(dt)
        discharge_dt = price_forecast['price'].idxmax()
        # Repay must occur after discharge and withing repay slot
        price_forecast = price_forecast.loc[discharge_dt:]
        price_forecast = self.define_repay_period(price_forecast)
        repay_dt = price_forecast['price'].idxmin()

        cop_ratio = (self.setting.high_pressure_cop - self.setting.baseline_cop) / \
                    (self.setting.baseline_cop - self.setting.low_pressure_cop)
        self.dispatch_schedule.add_period(
            DateRangePeriod(discharge_dt, discharge_dt + self.forecast_resolution)
        )
        repay_period = DateRangePeriod(repay_dt, repay_dt + self.forecast_resolution * cop_ratio)
        self.repay_schedule.add_period(
            repay_period
        )

    def schedule_retail_optimised_dispatch(
            self,
            dt: datetime,
    ):
        pass


@dataclass
class FanThrottleDispatcher(SettingsDispatcher):
    setting: FanThrottle = field(default=None)

    def schedule_market_optimised_dispatch(
            self,
            dt: datetime,
    ):
        price_forecast = self.market_prices.forecast(dt)
        discharge_dt = price_forecast['price'].idxmax()

        # Repay must occur after discharge and withing repay slot
        price_forecast = price_forecast.loc[discharge_dt:]
        price_forecast = self.define_repay_period(price_forecast)
        repay_dt = price_forecast['price'].idxmin()

        self.dispatch_schedule.add_period(
            DateRangePeriod(discharge_dt, discharge_dt + self.forecast_resolution)
        )
        repay_period = DateRangePeriod(repay_dt, repay_dt + self.forecast_resolution)
        self.repay_schedule.add_period(
            repay_period
        )

    def schedule_retail_optimised_dispatch(
            self,
            dt: datetime,
    ):
        pass
