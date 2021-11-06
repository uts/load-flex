from __future__ import annotations

from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import List
import numpy as np
from ts_tariffs.sites import MeterData
from ts_tariffs.tariffs import DemandCharge, TOUCharge

from dispatch_constraints import (
    DispatchConstraint,
    DispatchSchedule,
    SetPointProposal,
    SetPoint,
    PeakShaveSetPoint,
    DemandScenario, GenericSetPoint, TouPeakShaveComboSetPoint, SetPointSchedule, ThermalPeakShaveSetPoint,
)
from metering import ThermalLoadFlexMeter, DispatchFlexMeter
from storage import Battery, ThermalStorage
from time_series_utils import Forecaster, SpecificEvents, EventSchedule, PeriodSchedule, DateRangePeriod
from optimisers import PeakShave, TOUShiftingCalculator
from equipment import Storage, Dispatch
from wholesale_prices import MarketPrices


@dataclass
class Forecasters:
    charge: Forecaster
    discharge: Forecaster
    universal: Forecaster


@dataclass
class StorageController(ABC):
    name: str
    equipment: Storage
    forecasters: Forecasters
    dispatch_schedule: DispatchSchedule
    other_dispatch_constraints: List[DispatchConstraint]
    meter: DispatchFlexMeter
    setpoint: SetPoint
    dispatch_on: str

    @abstractmethod
    def update_setpoint(
            self,
            dt: datetime,
    ):
        """ Update setpoints for gross curve load shifting
        """
        pass

    def initialise_setpoint(self, dt: datetime):
        setpoint_schedule_event = SpecificEvents(tuple([dt]))
        event_setters = {
            'charge': self.setpoint.schedule.charge,
            'discharge': self.setpoint.schedule.discharge,
            'universal': self.setpoint.schedule.universal,
        }
        which_event = self.dispatch_schedule.which_setpoint(dt)
        event_setters[which_event].add_event(
            setpoint_schedule_event
        )
        self.update_setpoint(dt)

    def demand_at_t(self, dt: datetime):
        return self.meter.tseries.loc[dt][self.dispatch_on]

    def dispatch_proposal(self, demand_scenario: DemandScenario) -> Dispatch:
        raw_dispatch_proposal = self.setpoint.raw_dispatch_proposal(
            demand_scenario,
            self.dispatch_schedule
        )
        proposal = Dispatch.from_raw_float(raw_dispatch_proposal)
        for condition in self.other_dispatch_constraints:
            proposal = condition.limit_dispatch(
                demand_scenario,
                proposal,
            )
        return proposal

    def dispatch(self):
        for dt, demand in self.meter.tseries.iterrows():
            self.update_setpoint(dt)
            dispatch_proposal = self.dispatch_proposal(
                    DemandScenario(
                        demand[self.dispatch_on],
                        dt,
                        self.setpoint,
                        self.meter.tseries['balance_energy'].loc[dt]
                    )
                )
            dispatch = self.equipment.dispatch_request(dispatch_proposal, self.meter.sample_rate)
            self.dispatch_schedule.validate_dispatch(dispatch, dt)
            reportables = {
                'charge_setpoint': self.setpoint.charge_setpoint,
                'discharge_setpoint': self.setpoint.discharge_setpoint,
                'universal_setpoint': self.setpoint.universal_setpoint,
                **self.equipment.status()
            }
            self.meter.update_dispatch(
                dt,
                dispatch,
                self.dispatch_on,
                reportables,
            )
            self.setpoint.update_historical_net_demand(
                demand[self.dispatch_on] - dispatch.net_value
            )


@dataclass
class PeakShaveBatteryController(StorageController):
    setpoint: PeakShaveSetPoint
    equipment: Battery

    def __post_init__(self):
        if not self.setpoint.schedule.universal.event_occurrences:
            raise TypeError('Universal setpoint schedule events missing: '
                            'Peak shave setpoint requires schedule'
                            ' with events in universal schedule')
        self.initialise_setpoint(self.meter.first_datetime())

    def propose_setpoint(self, dt: datetime):
        forecast = self.forecasters.universal.look_ahead(
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

    def update_setpoint(self, dt: datetime):
        proposal = SetPointProposal()
        if self.setpoint.universal_due(dt):
            proposal.universal = self.propose_setpoint(dt)
        self.setpoint.set(proposal, dt)


@dataclass
class TouBatteryController(StorageController):
    setpoint: GenericSetPoint
    equipment: Battery

    def __post_init__(self):
        self.initialise_setpoint(self.meter.first_datetime())

    def propose_charge_setpoint(self, dt: datetime):
        forecast = self.forecasters.charge.look_ahead(
            self.meter.tseries,
            dt
        )
        demand_arr = forecast[self.dispatch_on].values

        return TOUShiftingCalculator.charge_setpoint(
            demand_arr,
            self.equipment.available_storage
        )

    def propose_discharge_setpoint(self, dt: datetime):
        forecast = self.forecasters.discharge.look_ahead(
            self.meter.tseries,
            dt
        )
        demand_arr = forecast[self.dispatch_on].values
        return TOUShiftingCalculator.calculate_setpoint(
            demand_arr,
            self.equipment.available_energy
        )

    def update_setpoint(
            self,
            dt: datetime,
    ):
        proposal = SetPointProposal()
        if self.setpoint.charge_due(dt):
            proposal.charge = self.propose_charge_setpoint(dt)
        if self.setpoint.discharge_due(dt):
            proposal.discharge = self.propose_discharge_setpoint(dt)
        self.setpoint.set(proposal, dt)


@dataclass
class TouPeakShaveComboBatteryController(TouBatteryController):
    setpoint: TouPeakShaveComboSetPoint
    equipment: Battery

    def __post_init__(self):
        self.initialise_setpoint(self.meter.first_datetime())


@dataclass
class ThermalStoragePeakShaveController(StorageController):
    setpoint: ThermalPeakShaveSetPoint
    equipment: ThermalStorage
    meter: ThermalLoadFlexMeter

    def __post_init__(self):
        pass

    def propose_setpoint(self, dt: datetime):
        gross_col = 'gross_mixed_electrical_and_thermal'
        sub_col = 'subload_energy'
        balance_col = 'balance_energy'
        thermal_forecast = self.forecasters.universal.look_ahead(
            self.meter.thermal_tseries,
            dt
        ).copy()
        elec_demand = self.forecasters.universal.look_ahead(
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

    def update_setpoint(
            self,
            dt: datetime
    ):
        if self.setpoint.universal_due(dt):
            proposal = SetPointProposal()
            proposal.universal = self.propose_setpoint(dt)
            self.setpoint.set(proposal, dt)


@dataclass
class WholesalePriceTranchBatteryController(StorageController):
    market_prices: MarketPrices
    tranche_energy: float = field(init=False)
    number_tranches: int = field(init=False)

    def __post_init__(self):
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
        self.dispatch_schedule.charge_schedule.add_periods(charge_periods)
        self.dispatch_schedule.discharge_schedule.add_periods(discharge_periods)

    def update_setpoint(
            self,
            dt: datetime
    ):
        if self.setpoint.schedule.universal.event_due(dt):
            self.set_dispatch_schedule(dt)
        timesetep_hours = self.meter.sample_rate / timedelta(hours=1)
        setpoint_proposal = SetPointProposal(
            charge=self.equipment.nominal_charge_capacity * timesetep_hours + self.demand_at_t(dt),
            discharge=self.equipment.nominal_discharge_capacity * timesetep_hours - self.demand_at_t(dt)
        )
        self.setpoint.set(setpoint_proposal)