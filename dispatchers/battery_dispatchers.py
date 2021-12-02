from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import numpy as np

from dispatch_control.setpoints import SetPointProposal
from dispatchers.dispatchers import StorageDispatcher, WholesalePriceTranchDispatcher
from equipment.storage import Battery
from time_series_tools.schedulers import DateRangePeriod
from optimisers import PeakShave, TOUShiftingCalculator


@dataclass
class PeakShaveBatteryDispatcher(StorageDispatcher):
    equipment: Battery

    def __post_init__(self):
        self._parent_post_init()
        if not self.controller.setpoints.setter_schedule.universal_params.event_occurrences:
            raise TypeError('Universal setpoint schedule events missing: '
                            'Peak shave setpoint requires schedule'
                            ' with events in universal schedule')
        # Ensure setpoints set from start datetime
        self.add_setpoint_set_event(
            universal_params_dt=self.meter.first_datetime()
        )

    def propose_setpoint(self, dt: datetime):
        forecast = self.controller.setpoints.universal_forecast(
            self.meter.tseries,
            dt
        )
        sorted_arr = np.sort(forecast[self.dispatch_on].values)
        peak_areas = PeakShave.cumulative_peak_areas(sorted_arr)
        index = PeakShave.peak_area_idx(
            peak_areas,
            self.equipment.available_energy
        )
        return np.flip(sorted_arr)[index]

    def schedule_dispatch_params(self, dt: datetime):
        proposal = SetPointProposal()
        if self.controller.setpoints.universal_due(dt):
            proposal.universal = self.propose_setpoint(dt)
        self.controller.setpoints.set_setpoints(proposal, dt)


@dataclass
class ConservativePeakShaveComboBatteryController(PeakShaveBatteryDispatcher):
    """ Adjusts universal setpoint according to proposal and historical maximum.

    This strategy reduces the depth of peak shaving attempted by limiting it
    to be only as good as historical achievement. This is specifically advantageous
    where demand tariffs are the primary concern and there is no advantage in peak shaving
    below the period's peak demand. The advantage is gained by reducing the available
    energy required to achieve the target peak - i.e. there is more likelihood of energy
    being available
    """
    equipment: Battery

    def __post_init__(self):
        self._parent_post_init()
        self.add_setpoint_set_event(
            universal_params_dt=self.meter.first_datetime()
        )

    def schedule_dispatch_params(self, dt: datetime):
        proposal = SetPointProposal()
        if self.controller.setpoints.universal_due(dt):
            proposal.universal = max(
                self.propose_setpoint(dt),
                self.historical_peak_demand
            )
        self.controller.setpoints.set_setpoints(proposal, dt)


@dataclass
class TouBatteryDispatcher(StorageDispatcher):
    equipment: Battery

    def __post_init__(self):
        self._parent_post_init()
        self.add_setpoint_set_event(
            charge_params_dt=self.meter.first_datetime(),
            discharge_params_dt = self.meter.first_datetime()
        )

    def propose_charge_setpoint(self, dt: datetime):
        forecast = self.controller.setpoints.charge_forecast(
            self.meter.tseries,
            dt
        )
        demand_arr = forecast[self.dispatch_on].values

        return TOUShiftingCalculator.charge_setpoint(
            demand_arr,
            self.equipment.available_storage
        )

    def propose_discharge_setpoint(self, dt: datetime):
        forecast = self.controller.setpoints.discharge_forecast(
            self.meter.tseries,
            dt
        )
        demand_arr = forecast[self.dispatch_on].values
        return TOUShiftingCalculator.calculate_setpoint(
            demand_arr,
            self.equipment.available_energy
        )

    def schedule_dispatch_params(
            self,
            dt: datetime,
    ):
        proposal = SetPointProposal()
        if self.controller.setpoints.charge_due(dt):
            proposal.charge = self.propose_charge_setpoint(dt)
        if self.controller.setpoints.discharge_due(dt):
            proposal.discharge = self.propose_discharge_setpoint(dt)
        self.controller.setpoints.set_setpoints(proposal, dt)


@dataclass
class TouPeakShaveComboBatteryController(TouBatteryDispatcher):
    equipment: Battery

    def __post_init__(self):
        self._parent_post_init()
        self.add_setpoint_set_event(
            charge_params_dt=self.meter.first_datetime(),
            discharge_params_dt = self.meter.first_datetime()
        )

    def schedule_dispatch_params(
            self,
            dt: datetime,
    ):
        proposal = SetPointProposal()
        if self.controller.setpoints.charge_due(dt):
            proposal.charge = min(
                self.propose_charge_setpoint(dt),
                self.historical_peak_demand
            )
        if self.controller.setpoints.discharge_due(dt):
            proposal.discharge = self.propose_discharge_setpoint(dt)
        self.controller.setpoints.set_setpoints(proposal, dt)


@dataclass
class WholesalePriceTranchBatteryDispatcher(WholesalePriceTranchDispatcher):
    def __post_init__(self):
        self._parent_post_init()
        if not self.equipment.nominal_charge_capacity == self.equipment.nominal_discharge_capacity:
            raise ValueError('Note that optimal dispatch for WholesalePriceTranchBatteryController '
                             'requires that charge and discharge capacities are equal')
        self.calculate_tranches()
        # self.initialise_setpoint(self.meter.first_datetime())

    def set_dispatch_schedule(self, dt: datetime):
        price_forecast = self.market_prices.forecast(dt)
        sorted_price_tseries = price_forecast.sort_values(by='price')

        if self.meter.sample_rate != self.forecast_resolution:
            price_forecast = price_forecast.resample(self.forecast_resolution).mean()

        number_dispatch_slots = int(self.number_tranches / 2)
        number_dispatch_pairs = min(int(len(price_forecast) / 2), number_dispatch_slots)

        charge_times = sorted_price_tseries.iloc[:number_dispatch_pairs, :].index
        discharge_times = sorted_price_tseries.iloc[-number_dispatch_pairs:, :].index
        charge_periods = list([DateRangePeriod(x, x + self.forecast_resolution) for x in charge_times])
        discharge_periods = list([DateRangePeriod(x, x + self.forecast_resolution) for x in discharge_times])

        self.controller.update_primary_dispatch_schedule(
            charge_periods,
            discharge_periods,
            clean_slate=True
        )

    def schedule_dispatch_params(
            self,
            dt: datetime
    ):
        if self.controller.primary_dispatch_schedule.setter_schedule.universal_params_due(dt):
            self.set_dispatch_schedule(dt)