from dataclasses import dataclass
from datetime import datetime, timedelta

from equipment.equipment import Dispatch
from equipment.settings_adjustments import CompressorSuctionPressure
from time_series_tools.metering import DispatchFlexMeter
from time_series_tools.schedulers import PeriodSchedule, EventSchedule, DateRangePeriod
from time_series_tools.wholesale_prices import MarketPrices


@dataclass
class CompressorSuctionPressureDispatcher:
    name: str
    meter: DispatchFlexMeter
    setting: CompressorSuctionPressure
    setter_schedule: EventSchedule
    market_prices: MarketPrices
    dispatch_on: str
    dispatch_schedule: PeriodSchedule = None
    repay_schedule: PeriodSchedule = None
    forecast_resolution: timedelta = timedelta(hours=0.5)

    def __post_init__(self):
        self.dispatch_schedule = PeriodSchedule([])
        self.repay_schedule = PeriodSchedule([])

    def optimise_dispatch_params(
            self,
            dt: datetime,
    ):
        price_forecast = self.market_prices.forecast(dt)
        discharge_dt = price_forecast['price'].idxmax()
        # Repay must occur after discharge
        price_forecast = price_forecast.loc[discharge_dt:]
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
        x = 1

    def dispatch(self):
        for dt, demand in self.meter.tseries.iterrows():
            if self.setter_schedule.event_due(dt):
                self.optimise_dispatch_params(dt)
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
