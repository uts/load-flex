from dataclasses import dataclass
from datetime import datetime, timedelta
import numpy as np
from ts_tariffs.sites import MeterData

from dispatch_control.setpoints import DemandScenario
from dispatchers.dispatchers import Dispatcher
from equipment.heat_pumps import HeatingHeatPump
from time_series_tools.metering import ThermalLoadFlexMeter, PowerFlexMeter
from time_series_tools.schedulers import DateRangePeriod
from time_series_tools.wholesale_prices import MarketPrices


@dataclass
class ThermalSupply:
    raw_cost_of_energy: float
    efficiency: float

    @property
    def dispatch_cost(self):
        return self.raw_cost_of_energy / self.efficiency


@dataclass
class HeatPumpDispatcher(Dispatcher):
    equipment: HeatingHeatPump
    meter: MeterData
    market_prices: MarketPrices
    base_supply: ThermalSupply
    forecast_resolution: timedelta = timedelta(hours=0.5)

    @property
    def price_signal(self):
        """ Cost of electrical energy at which heat pump is more
        economical
        """
        return \
            self.base_supply.dispatch_cost \
            * self.equipment.cop

    def schedule_economic_dispatch(self, dt: datetime):
        """ Identify times when market prices make heat pump more economical than
        base thermal supply
        """
        price_forecast = self.market_prices.forecast(dt)
        if self.meter.sample_rate != self.forecast_resolution:
            price_forecast = price_forecast.resample(self.forecast_resolution).mean()

        # get list of dispatch datetimes
        cost_effective_hp_times = price_forecast[price_forecast['price'] < self.price_signal].index

        # Where cost of heat pump is lower than gas, schedule dispatch
        discharge_periods = list([
            DateRangePeriod(x, x + self.forecast_resolution)
            for x in cost_effective_hp_times
        ])
        self.controller.update_primary_dispatch_schedule(
            [],
            discharge_periods,
            clean_slate=True
        )

    def schedule_dispatch_params(
            self,
            dt: datetime,
    ):
        self.schedule_economic_dispatch(dt)
