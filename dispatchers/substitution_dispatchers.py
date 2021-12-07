from dataclasses import dataclass
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

from dispatchers.dispatchers import Dispatcher
from equipment.heat_pumps import HeatPump
from time_series_tools.metering import GasToElectricityFlexMeter
from time_series_tools.wholesale_prices import MarketPrices


@dataclass
class ThermalSupply:
    raw_cost_of_energy: float
    efficiency: float

    @property
    def dispatch_cost(self):
        return self.raw_cost_of_energy / self.efficiency


@dataclass
class HeatPumpWholesaleDispatcher(Dispatcher):
    equipment: HeatPump
    meter: GasToElectricityFlexMeter
    market_prices: MarketPrices
    base_supply: ThermalSupply

    @property
    def price_signal(self):
        """ Cost of electrical energy at which heat pump is more
        economical
        """
        return \
            self.base_supply.dispatch_cost \
            * self.equipment.cop

    def schedule_dispatch_params(
            self,
            dt: datetime,
    ):
        """
        """
        pass

    def dispatch(self):

        dispatch_proposal = np.where(
            self.market_prices.tseries['price'] < self.price_signal,
            self.equipment.max_dispatch(self.meter.sample_rate).discharge,
            0.0
        )
        dispatch = pd.Series(np.clip(dispatch_proposal, 0.0, self.meter.tseries[self.dispatch_on]))
        self.meter.consolidate_vector_updates(discharge=dispatch)


@dataclass
class HeatPumpRetailDispatcher(Dispatcher):
    equipment: HeatPump
    meter: GasToElectricityFlexMeter
    market_prices: MarketPrices
    base_supply: ThermalSupply

    def schedule_dispatch_params(
            self,
            dt: datetime,
    ):
        """
        """
        pass

    def dispatch(self):
        self.meter.consolidate_vector_updates(
            discharge = self.meter.tseries[self.dispatch_on]
        )
