from __future__ import annotations

from dataclasses import dataclass
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List
import numpy as np
from ts_tariffs.tariffs import DemandCharge, TOUCharge

from dispatch_constraints import (
    DispatchConstraint,
    DispatchSchedule,
    SetPointProposal,
    SetPoint,
    PeakShaveSetPoint,
    DemandScenario, GenericSetPoint, TouPeakShaveComboSetPoint,
)
from metering import ThermalLoadFlexMeter, DispatchFlexMeter
from storage import Battery, ThermalStorage
from time_series_utils import Forecaster, SpecificEvents
from optimisers import PeakShave, TOUShiftingCalculator
from equipment import Storage, Dispatch


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
        """
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

    def dispatch_proposal(self, demand_scenario: DemandScenario) -> float:
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
                    DemandScenario(demand[self.dispatch_on], dt, self.setpoint)
                )
            dispatch = self.equipment.dispatch_request(dispatch_proposal)
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
                demand.loc[dt, self.dispatch_on] - dispatch.net_value
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
    setpoint: PeakShaveSetPoint
    equipment: ThermalStorage
    meter: ThermalLoadFlexMeter

    def __post_init__(self):

        # Add cols for setpoint calcs
        self.meter.thermal_tseries['gross_mixed_electrical_and_thermal'] =\
            self.meter.thermal_tseries['subload_energy']\
            + self.meter.tseries['balance_energy']

    def propose_setpoint(self, dt: datetime):
        calc_forecast = self.forecasters.universal.look_ahead(
            self.meter.tseries,
            dt
        )
        thermal_forecast = self.forecasters.universal.look_ahead(
            self.meter.thermal_tseries,
            dt
        )
        calc_forecast['gross_mixed_electrical_and_thermal'] \
            = thermal_forecast['gross_mixed_electrical_and_thermal']
        calc_forecast['thermal_subload_energy'] = thermal_forecast['subload_energy']
        calc_forecast.sort_values('demand_energy', inplace=True)
        calc_forecast.reset_index(inplace=True, drop=True)

        limiting_setpoint_idx = calc_forecast['balance_energy'].idxmax()
        proposal = PeakShave.sub_load_peak_shave_limit(
            calc_forecast,
            limiting_setpoint_idx,
            self.equipment.available_energy,
            'gross_mixed_electrical_thermal',
            'thermal_subload_energy'
        )
        return proposal

    def update_setpoint(
            self,
            dt: datetime
    ):
        proposal = SetPointProposal()
        proposal.universal = self.propose_setpoint(dt)
        self.setpoint.set(proposal, dt)
