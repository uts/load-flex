from __future__ import annotations

from dataclasses import dataclass
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Type, List, Union, Tuple
from numbers import Number
import numpy as np
import pandas as pd
from ts_tariffs.tariffs import TOUCharge, DemandCharge

from metering import ThermalLoadFlexMeter, DispatchFlexMeter
from storage import Battery, ThermalStorage
from time_series_utils import Scheduler, Forecaster, PeakShaveTools
from equipment import Equipment, Storage


@dataclass
class DemandScenario:
    demand: float
    dt: datetime


@dataclass
class DispatchCondition(ABC):
    @abstractmethod
    def limit_dispatch(
            self,
            controller: Controller,
            demand_scenario,
            proposal: float
    ) -> float:
        pass


@dataclass
class NonChargeHoursCondition(DispatchCondition):
    non_charge_hours: Tuple[int]

    def limit_dispatch(
            self,
            controller: Controller,
            demand_scenario,
            proposal: float
    ) -> float:
        ''' Set charge to 0.0 if hour is in non-charge hours.
        (Negative dispatch proposal is discharge, positive is charge)
        '''
        proposal = min(0.0, proposal) \
            if demand_scenario.dt.hour in self.non_charge_hours \
            else proposal
        return proposal


@dataclass
class NonDischargeHoursCondition(DispatchCondition):
    non_discharge_hours: Tuple[int]

    def limit_dispatch(
            self,
            controller: Controller,
            demand_scenario,
            proposal: float
    ) -> float:
        """ Set discharge to 0.0 if hour is in non-discharge hours.
        (Negative dispatch proposal is discharge, positive is charge)
        """
        proposal = max(0.0, proposal) \
            if demand_scenario.dt.hour in self.non_discharge_hours \
            else proposal
        return proposal


@dataclass
class OffPeakIncreasedPeakCondition(DispatchCondition):
    tou_tariff: TOUCharge
    demand_tariff: DemandCharge
    sample_rate: timedelta

    @property
    def demand_vs_tou_breakeven_point(self) -> float:
        """ Breakeven point: The quantum of increased demand (as energy) in a
        single timestep where the cost of the increase in the peak is equal to
        the savings from TOU shifting (peak to offpeak) is equivalent

        Answers the question: When is it cost effective to increase peak demand during
        offpeak times for the sake of TOU load shifting?

        * NOT A VERY SMART OPTIMISER:
         - Assumes energy used to charge in offpeak is always discharged as peak tou
         - assumes non-tou based demand charge
        """
        tou_shift_savings = \
            max(self.tou_tariff.tou.bin_rates) - min(self.tou_tariff.tou.bin_rates)
        sample_rate_hours = self.sample_rate / timedelta(hours=1)
        return tou_shift_savings * sample_rate_hours / self.demand_tariff.rate

    def limit_dispatch(
            self,
            controller: Controller,
            demand_scenario,
            proposal: float
    ) -> float:
        """ Check if charging will increase peak for demand charge period - if yes, check if
        it is economical to do so by calculating balance of TOU and demand tariffs. If not
        economical, throttle charge rate to the point where it is economical
        """
        breach = max(0.0, demand_scenario.demand + proposal - controller.dispatch_threshold)
        proposal = min(self.demand_vs_tou_breakeven_point, breach)
        return proposal


@dataclass
class Controller(ABC):
    name: str
    equipment: Equipment = None
    forecaster: Forecaster = None
    forecast_scheduler: Scheduler = None
    dispatch_conditions: List[DispatchCondition] = None
    meter: DispatchFlexMeter = None
    dispatch_threshold: float = 0.0

    @abstractmethod
    def dispatch(self):
        pass


@dataclass
class StorageController(Controller):
    equipment: Storage = None
    dispatch_on: str = None

    def __post_init__(self):
        # Initialise limits
        if not self.dispatch_threshold:
            self.set_limit(
                self.meter.tseries.first_valid_index(),
            )

    @abstractmethod
    def set_limit(
            self,
            dt: datetime,
    ):
        """ """
        pass

    def dispatch_proposal(self, demand_scenario: DemandScenario) -> float:
        proposal = self.dispatch_threshold - demand_scenario.demand
        for condition in self.dispatch_conditions:
            proposal = condition.limit_dispatch(self, demand_scenario, proposal)
        return proposal

    def dispatch(self):
        for dt, demand in self.meter.tseries.iterrows():
            if self.forecast_scheduler.event_due(dt):
                self.set_limit(dt)
            dispatch = self.equipment.energy_request(
                self.dispatch_proposal(
                    DemandScenario(demand[self.dispatch_on], dt)
                )
            )
            reportables = {
                'dispatch_threshold': self.dispatch_threshold,
                **self.equipment.status()
            }
            self.meter.update_dispatch(
                dt,
                max(dispatch, 0.0),
                min(dispatch, 0),
                reportables
            )


@dataclass
class SimpleBatteryPeakShaveController(StorageController):
    equipment: Battery = None

    def set_limit(
            self,
            dt: datetime
    ):
        forecast = self.forecaster.look_ahead(
            self.meter.tseries,
            dt
        )
        sorted_arr = np.sort(forecast[self.dispatch_on].values)
        peak_areas = PeakShaveTools.cumulative_peak_areas(sorted_arr)
        index = PeakShaveTools.peak_area_idx(
            peak_areas,
            self.equipment.available_energy
        )
        proposed_limit = np.flip(sorted_arr)[index]
        self.dispatch_threshold = max(self.dispatch_threshold, proposed_limit)


@dataclass
class SimpleBatteryTOUShiftController(StorageController):
    equipment: Battery = None

    def set_limit(
            self,
            dt: datetime
    ):
        forecast = self.forecaster.look_ahead(
            self.meter.tseries,
            dt
        )
        sorted_arr = np.sort(forecast[self.dispatch_on].values)
        peak_areas = PeakShaveTools.cumulative_peak_areas(sorted_arr)
        index = PeakShaveTools.peak_area_idx(
            peak_areas,
            self.equipment.available_energy
        )
        proposed_limit = np.flip(sorted_arr)[index]
        self.dispatch_threshold = proposed_limit


@dataclass
class ThermalStorageController(StorageController):
    equipment: ThermalStorage = None
    meter: ThermalLoadFlexMeter = None
    dispatch_on: str = 'equivalent_thermal_energy'

    def set_limit(
            self,
            dt: datetime
    ):
        forecast = self.forecaster.look_ahead(
            self.meter.tseries,
            dt
        )
        forecast.sort_values('gross_electrical_energy', inplace=True)
        forecast.reset_index(inplace=True, drop=True)

        limiting_threshold_idx = forecast['other_electrical_energy'].idxmax()
        forecast['gross_mixed_electrical_thermal'] = \
            forecast['other_electrical_energy'] + forecast['equivalent_thermal_energy']
        proposed_limit = PeakShaveTools.sub_load_peak_shave_limit(
            forecast,
            limiting_threshold_idx,
            self.equipment.available_energy,
            'gross_mixed_electrical_thermal',
            'equivalent_thermal_energy'
        )
        self.dispatch_threshold = max(self.dispatch_threshold, proposed_limit)
