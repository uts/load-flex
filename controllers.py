from __future__ import annotations

from dataclasses import dataclass
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Type, List, Union, Tuple
from numbers import Number
import numpy as np
import pandas as pd
from ts_tariffs.sites import ElectricityMeterData, MeterData
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
class ChargeHoursCondition(DispatchCondition):
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
class DischargeHoursCondition(DispatchCondition):
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
                self.forecaster.look_ahead(
                    self.meter.meter.meter_ts,
                    self.meter.meter.meter_ts.first_valid_index()
                ),
                self.equipment.available_energy
            )

    @abstractmethod
    def set_limit(
            self,
            demand_forecast: Union[List[Number], np.ndarray, pd.Series],
            area: float
    ):
        """ """
        pass

    def dispatch_proposal(self, demand_scenario: DemandScenario) -> float:
        proposal = self.dispatch_threshold - DemandScenario.demand
        for condition in self.dispatch_conditions:
            proposal = condition.limit_dispatch(self, demand_scenario, proposal)
        return proposal

    def dispatch(self):
        for dt, demand in self.meter.meter_ts.iteritems():
            if self.forecast_scheduler.event_due(dt):
                self.set_limit(
                    self.forecaster.look_ahead(
                        self.meter.meter_ts[self.dispatch_on],
                        dt
                    ),
                    self.equipment.available_energy
                )
            dispatch = self.equipment.energy_request(
                self.dispatch_proposal(
                    DemandScenario(demand[self.dispatch_on], dt)
                )
            )
            reportables = {
                'peak_threshold': self.dispatch_threshold,
                **self.equipment.status()
            }
            self.meter.update_dispatch(
                dt,
                max(dispatch, 0.0),
                min(dispatch, 0),
                reportables
            )


@dataclass
class SimpleBatteryController(StorageController):
    equipment: Battery = None

    def set_limit(
            self,
            demand_forecast: Union[List[Number], np.ndarray, pd.Series],
            area: float
    ):
        sorted_arr = np.sort(
            self.meter.meter_ts[self.dispatch_on].values
        )
        peak_areas = PeakShaveTools.cumulative_peak_areas(sorted_arr)
        index = PeakShaveTools.peak_area_idx(peak_areas, area)
        proposed_limit = np.flip(sorted_arr)[index]
        self.peak_threshold = max(self.peak_threshold, proposed_limit)


@dataclass
class ThermalStorageController(StorageController):
    equipment: ThermalStorage = None
    meter: ThermalLoadFlexMeter = None
    dispatch_on: str = 'equivalent_thermal_energy'

    def set_limit(
            self,
            demand_arr: Union[List[Number], np.ndarray, pd.Series],
            area: float
    ):
        ts = self.meter.meter_ts.copy()
        ts.sort_values('gross_electrical_energy', inplace=True)
        ts.reset_index(inplace=True, drop=True)

        limiting_threshold_idx = ts['other_electrical_energy'].idxmax()
        ts['gross_mixed_electrical_thermal'] = \
            ts['other_electrical_energy'] + ts['equivalent_thermal_energy']
        proposed_limit = PeakShaveTools.sub_load_peak_shave_limit(
            ts,
            limiting_threshold_idx,
            area,
            'gross_mixed_electrical_thermal',
            'equivalent_thermal_energy'
        )
        self.peak_threshold = max(self.peak_threshold, proposed_limit)