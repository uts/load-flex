from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from dispatch_control.setpoints import SetPointProposal
from dispatchers.dispatchers import StorageDispatcher, WholesalePriceTranchDispatcher
from equipment.storage import ThermalStorage
from optimisers import PeakShave
from time_series_tools.metering import ThermalLoadFlexMeter
from time_series_tools.schedulers import DateRangePeriod
from time_series_tools.wholesale_prices import MarketPrices

from time import time


@dataclass
class ThermalStoragePeakShaveDispatcher(StorageDispatcher):
    equipment: ThermalStorage
    meter: ThermalLoadFlexMeter

    def __post_init__(self):
        self._parent_post_init()
        self.add_setpoint_set_event(
            universal_params_dt=self.meter.first_datetime()
        )

    def propose_setpoint(self, dt: datetime):
        gross_col = 'gross_mixed_electrical_and_thermal'
        sub_col = 'subload_energy'
        balance_col = 'balance_energy'
        thermal_forecast = self.controller.setpoints.universal_forecast(
            self.meter.thermal_tseries,
            dt
        ).copy()
        elec_demand = self.controller.setpoints.universal_forecast(
            self.meter.tseries,
            dt
        )
        thermal_forecast['balance_energy'] = elec_demand['balance_energy']
        sort_order = np.argsort(elec_demand['demand_energy'])
        thermal_forecast.reset_index(inplace=True, drop=True)
        proposal = PeakShave.sub_load_peak_shave_limit(
            thermal_forecast.iloc[sort_order],
            self.equipment.available_energy,
            gross_col,
            sub_col,
            balance_col,
        )
        return proposal

    def optimise_dispatch_params(
            self,
            dt: datetime
    ):
        if self.controller.setpoints.universal_due(dt):
            proposal = SetPointProposal()
            proposal.universal = self.propose_setpoint(dt)
            self.controller.setpoints.set_setpoints(proposal, dt)


@dataclass
class WholesalePriceTranchThermalDispatcher(WholesalePriceTranchDispatcher):
    market_prices: MarketPrices
    forecast_resolution: timedelta = timedelta(hours=0.5)
    tranche_energy: float = None
    number_tranches: int = None

    def __post_init__(self):
        self._parent_post_init()
        self.calculate_tranches()

    def set_dispatch_schedule(self, dt):

        subload_forecast = self.market_prices.forecaster.look_ahead(
            self.meter.tseries['subload_energy'],
            dt
        )
        subload_forecast =subload_forecast.resample(self.forecast_resolution).sum()
        price_forecast = self.market_prices.forecast(dt)
        price_forecast = price_forecast.resample(self.forecast_resolution).mean()

        price_forecast_charging = price_forecast
        # price_forecast_discharging should only include datetimes
        # where subload is present
        price_forecast_discharging = price_forecast[subload_forecast > 0.0]
        sorted_price_charging = price_forecast_charging.sort_values(by='price')
        sorted_price_discharging = price_forecast_discharging.sort_values(by='price')

        number_dispatch_slots = int(self.number_tranches / 2)
        number_dispatch_pairs = min(int(len(price_forecast) / 2), number_dispatch_slots)
        charge_times = sorted_price_charging.iloc[:number_dispatch_pairs, :].index
        discharge_times = sorted_price_discharging.iloc[-number_dispatch_pairs:, :].index

        charge_periods = list([DateRangePeriod(x, x + self.forecast_resolution) for x in charge_times])
        discharge_periods = list([DateRangePeriod(x, x + self.forecast_resolution) for x in discharge_times])

        self.controller.update_primary_dispatch_schedule(
            charge_periods,
            discharge_periods,
            clean_slate=True
        )

    def optimise_dispatch_params(
            self,
            dt: datetime
    ):
        if self.controller.primary_dispatch_schedule.setter_schedule.universal_params_due(dt):
            self.set_dispatch_schedule(dt)
