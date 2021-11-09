from __future__ import annotations

from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import List
import numpy as np

from dispatch_control.controllers import ParamController
from dispatch_control.dispatch_schedulers import (
    DispatchConstraintSchedule, )
from dispatch_control.constraints import DispatchConstraint, DispatchConstraints
from dispatch_control.setpoints import SetPointProposal, DemandScenario
from metering import ThermalLoadFlexMeter, DispatchFlexMeter
from storage import Battery, ThermalStorage
from time_tools.schedulers import DateRangePeriod
from optimisers import PeakShave, TOUShiftingCalculator
from equipment import Storage, Dispatch
from wholesale_prices import MarketPrices


@dataclass
class StorageDispatcher(ABC):
    name: str
    equipment: Storage
    dispatch_constraint_schedule: DispatchConstraintSchedule
    special_constraints: DispatchConstraints
    meter: DispatchFlexMeter
    controller: ParamController
    dispatch_on: str

    historical_peak_demand: float = field(init=False, default=0.0)
    historical_min_demand: float = field(init=False, default=0.0)

    def __post_init__(self):
        self._parent_post_init()

    def _parent_post_init(self):
        """ Convenience method for preventing override of base class __post_init__

        Where child classes overide the __post_init__ method, they should call this method
        to ensure parent post init operations occur
        """
        pass

    @abstractmethod
    def optimise_dispatch_params(
            self,
            dt: datetime,
    ):
        """ Update setpoints for gross curve load shifting
        """
        pass

    def add_setpoint_set_event(
            self,
            charge_params_dt: datetime = None,
            discharge_params_dt: datetime = None,
            universal_params_dt: datetime = None,
    ):
        self.controller.setpoints.add_setter_events(
            charge_params_dt,
            discharge_params_dt,
            universal_params_dt,
        )

    def demand_at_t(self, dt: datetime):
        return self.meter.tseries.loc[dt][self.dispatch_on]

    def setpoint_dispatch_proposal(self, demand_scenario: DemandScenario) -> Dispatch:
        return self.controller.setpoints.dispatch_proposal(
            demand_scenario,
            self.dispatch_constraint_schedule
        )

    def scheduled_dispatch_proposal(self, dt: datetime) -> Dispatch:
        return self.controller.dispatch_schedule.dispatch_proposal(dt)

    def apply_special_constraints(self, proposal: Dispatch) -> Dispatch:
        return self.special_constraints.constrain(proposal)

    def update_historical_net_demand(self, net_demand: float):
        self.historical_peak_demand = max(net_demand, self.historical_peak_demand)
        self.historical_min_demand = min(net_demand, self.historical_peak_demand)

    def dispatch(self):
        for dt, demand in self.meter.tseries.iterrows():
            self.optimise_dispatch_params(dt)
            # Only invoke setpoints if no scheduled dispatch
            dispatch_proposal = self.scheduled_dispatch_proposal(dt)
            if dispatch_proposal.no_dispatch:
                demand_scenario = DemandScenario(
                    demand[self.dispatch_on],
                    dt,
                    self.meter.tseries['balance_energy'].loc[dt]
                )
                dispatch_proposal = self.setpoint_dispatch_proposal(demand_scenario)

            dispatch_proposal = self.apply_special_constraints(dispatch_proposal)

            dispatch = self.equipment.dispatch_request(dispatch_proposal, self.meter.sample_rate)
            self.dispatch_constraint_schedule.validate_dispatch(dispatch, dt)
            reportables = {
                'charge_setpoint': self.controller.setpoints.charge_setpoint,
                'discharge_setpoint': self.controller.setpoints.discharge_setpoint,
                'universal_setpoint': self.controller.setpoints.universal_setpoint,
                **self.equipment.status()
            }
            self.meter.update_dispatch(
                dt,
                dispatch,
                self.dispatch_on,
                reportables,
            )
            self.update_historical_net_demand(
                demand[self.dispatch_on] - dispatch.net_value
            )


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

    def optimise_dispatch_params(self, dt: datetime):
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

    def optimise_dispatch_params(self, dt: datetime):
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

    def optimise_dispatch_params(
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

    def optimise_dispatch_params(
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
class WholesalePriceTranchBatteryDispatcher(StorageDispatcher):
    market_prices: MarketPrices
    tranche_energy: float = field(init=False)
    number_tranches: int = field(init=False)

    def __post_init__(self):
        self._parent_post_init()
        if not self.equipment.nominal_charge_capacity == self.equipment.nominal_discharge_capacity:
            raise ValueError('Note that optimal dispatch for WholesalePriceTranchBatteryController '
                             'requires that charge and discharge capacities are equal')
        self.calculate_tranches()
        # self.initialise_setpoint(self.meter.first_datetime())

    def calculate_tranches(self):
        """Tranches defined by how much energy can be dispatched in a single time step and how
        much storage capacity the battery has (assume smallest of charge or discharge rates)
        """
        time_step_hours = self.meter.sample_rate / timedelta(hours=1)
        dispatch_rate = min(
            self.equipment.nominal_charge_capacity,
            self.equipment.nominal_discharge_capacity
        )

        self.tranche_energy = dispatch_rate * time_step_hours
        # Need positive number of whole tranches as they will be allocated
        # equally to charge and discharge - this will leave remainder unallocated
        self.number_tranches = int(self.equipment.storage_capacity / self.tranche_energy)
        if self.number_tranches % 2 != 0:
            self.number_tranches -= 1

    def set_dispatch_schedule(self, dt):
        price_forecast = self.market_prices.forecast(dt)
        sorted_price_tseries = price_forecast.sort_values(by='price')
        number_dispatch_pairs = int(self.number_tranches / 2)
        charge_times = sorted_price_tseries.iloc[:number_dispatch_pairs, :].index
        discharge_times = sorted_price_tseries.iloc[-number_dispatch_pairs:, :].index
        charge_periods = list([DateRangePeriod(x, x + self.meter.sample_rate) for x in charge_times])
        discharge_periods = list([DateRangePeriod(x, x + self.meter.sample_rate) for x in discharge_times])
        self.controller.append_dispatch_schedule(
            charge_periods,
            discharge_periods
        )

    def optimise_dispatch_params(
            self,
            dt: datetime
    ):
        if self.controller.dispatch_schedule.setter_schedule.universal_params_due(dt):
            self.set_dispatch_schedule(dt)