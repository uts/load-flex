from __future__ import annotations

from dataclasses import dataclass
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import List, Tuple
import numpy as np
from ts_tariffs.tariffs import TOUCharge, DemandCharge

from metering import ThermalLoadFlexMeter, DispatchFlexMeter
from storage import Battery, ThermalStorage
from time_series_utils import Schedule, Forecaster, PeakShaveTools, TOUShiftingCalculator
from equipment import Equipment, Storage, Dispatch


@dataclass
class TwinScheduler:
    charge_threshold: Schedule
    discharge_threshold: Schedule

    def charge_threshold_due(self, dt):
        return self.charge_threshold.event_due(dt)

    def discharge_threshold_due(self, dt):
        return self.discharge_threshold.event_due(dt)


@dataclass
class DemandScenario:
    demand: float
    dt: datetime


@dataclass
class DispatchConstraint(ABC):
    @abstractmethod
    def limit_dispatch(
            self,
            controller: Controller,
            demand_scenario: DemandScenario,
            proposal: Dispatch
    ) -> Dispatch:
        pass


@dataclass
class HoursConstraint(DispatchConstraint):
    """ Defines hours when charging/discharging are permitted
    """
    charge_hours: Tuple[int] = None
    discharge_hours: Tuple[int] = None

    def limit_dispatch(
            self,
            controller: Controller,
            demand_scenario: DemandScenario,
            proposal: Dispatch
    ) -> Dispatch:
        """
        """
        hour = demand_scenario.dt.hour
        if self.charge_hours:
            if hour not in self.charge_hours:
                proposal.charge = 0.0
        if self.discharge_hours:
            if hour not in self.discharge_hours:
                proposal.discharge = 0.0
        return proposal


@dataclass
class DemandChargeVsTouPeakConstraint(DispatchConstraint):
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
            demand_scenario: DemandScenario,
            proposal: Dispatch
    ) -> Dispatch:
        """ Check if charging will increase peak for demand charge period - if yes, check if
        it is economical to do so by calculating balance of TOU and demand tariffs. If not
        economical, throttle charge rate to the point where it is economical
        """
        breach = max(
            0.0,
            demand_scenario.demand + proposal.charge - controller.dispatch_threshold.value
        )
        proposal.charge = min(self.demand_vs_tou_breakeven_point, breach)
        return proposal


@dataclass
class DispatchThreshold(ABC):
    historical_peak_demand: float
    historical_min_demand: float
    value: float = None

    def update_historical_net_demand(self, net_demand: float):
        self.historical_peak_demand = max(net_demand, self.historical_peak_demand)
        self.historical_min_demand = min(net_demand, self.historical_peak_demand)

    @abstractmethod
    def set_threshold(
            self,
            proposal: float,
            dt,
    ):
        pass


@dataclass
class PeakShaveDispatchThreshold(DispatchThreshold):
    """ Sets charge and discharge thresholds equally according to
        historical maximum.

    This strategy reduces the depth of peak shaving attempted by limiting it
    to be only as good as historical achievement. This is specifically advantageous
    where demand tariffs are the primary concern and there is no advantage in peak shaving
    below the period's peak demand. The advantage is gained by reducing the available
    energy required to achieve the target peak - i.e. there is more likelihood of energy
    being available
    """
    def set_threshold(
            self,
            proposal: float,
            dt,
    ):
        self.value = max(
            proposal,
            self.historical_peak_demand
        )


@dataclass
class PeakShaveTOUDispatchThreshold(DispatchThreshold):
    def set_threshold(
            self,
            proposal: float,
            dt,
    ):
        self.value = proposal


@dataclass
class ThresholdConditions:
    hours: Tuple[int]
    cap: float
    forecast_window: timedelta


@dataclass
class ExplicitCapsThreshold(DispatchThreshold):
    charge_conditions: ThresholdConditions = None
    discharge_conditions: ThresholdConditions = None

    def set_threshold(
            self,
            proposal: float,
            dt,
    ):
        self.value = proposal
        if self.charge_conditions:
            if dt.hour in self.charge_conditions.hours:
                self.value = self.charge_conditions.cap
        if self.discharge_conditions:
            if dt.hour in self.discharge_conditions.hours:
                self.value = self.discharge_conditions.cap


@dataclass
class Controller(ABC):
    name: str
    equipment: Equipment = None
    forecaster: Forecaster = None
    threshold_schedule: Schedule = None
    dispatch_conditions: List[DispatchConstraint] = None
    meter: DispatchFlexMeter = None
    dispatch_threshold: DispatchThreshold = None

    @abstractmethod
    def dispatch(self):
        pass


@dataclass
class StorageController(Controller):
    equipment: Storage = None
    dispatch_on: str = None

    def __post_init__(self):
        # Initialise limits
        if not self.dispatch_threshold.value:
            if self.equipment.state_of_charge:
                self.set_threshold(
                    self.meter.first_datetime(),
                )
            else:
                forecast = self.forecaster.look_ahead(
                    self.meter.tseries,
                    self.meter.first_datetime()
                )
                self.dispatch_threshold.set_threshold(forecast[self.dispatch_on].mean())


    @abstractmethod
    def set_threshold(
            self,
            dt: datetime,
    ):
        """
        """
        pass

    def dispatch_proposal(self, demand_scenario: DemandScenario) -> float:
        proposal = Dispatch.from_raw_float(
            demand_scenario.demand - self.dispatch_threshold.value
        )
        for condition in self.dispatch_conditions:
            proposal = condition.limit_dispatch(self, demand_scenario, proposal)
        return proposal

    def dispatch(self):
        for dt, demand in self.meter.tseries.iterrows():
            self.set_threshold(dt)
            proposal = self.dispatch_proposal(
                    DemandScenario(demand[self.dispatch_on], dt)
                )
            dispatch = self.equipment.dispatch_request(proposal)
            reportables = {
                'dispatch_threshold': self.dispatch_threshold.value,
                **self.equipment.status()
            }
            flexed_net = self.meter.update_dispatch(
                dt,
                dispatch,
                self.dispatch_on,
                reportables,
                return_net=True
            )
            self.dispatch_threshold.update_historical_net_demand(
                flexed_net
            )


@dataclass
class SimpleBatteryPeakShaveController(StorageController):
    equipment: Battery = None

    def propose_threshold(self, dt: datetime):
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
        return np.flip(sorted_arr)[index]

    def propose_charge_threshold(self, dt: datetime):
        """ Sets a charge limit in order to completely charge battery
        but to also spread the charging across the charge hours, rather
        than in one hit
        """
        forecast = self.forecaster.look_ahead(
            self.meter.tseries,
            dt
        )
        inverted_arr =\
            forecast[self.dispatch_on].values.max() \
            - forecast[self.dispatch_on].values
        sorted_arr = np.sort(inverted_arr)
        peak_areas = PeakShaveTools.cumulative_peak_areas(sorted_arr)
        index = PeakShaveTools.peak_area_idx(
            peak_areas,
            self.equipment.available_storage
        )
        proposal = forecast[self.dispatch_on].values.max() - np.flip(sorted_arr)[index]
        # if proposed threshold is too much for charge capacity to deliver,
        # just base on charge capacity
        if sorted_arr.max() - proposal > self.equipment.nominal_charge_capacity:
            proposal = max(0.0, sorted_arr.max() - self.equipment.nominal_charge_capacity)
        return proposal

    def set_threshold(self, dt: datetime):
        if self.threshold_schedule.event_due(dt):
            proposal = self.propose_threshold(dt)
        else:
            proposal = self.dispatch_threshold.value
        self.dispatch_threshold.set_threshold(proposal, dt)


@dataclass
class TouController(StorageController):
    charge_conditions: ThresholdConditions = None
    discharge_conditions: ThresholdConditions = None
    threshold_schedule: TwinScheduler = None

    def propose_threshold(self, arr: np.ndarray):
        sorted_arr = np.sort(arr)
        peak_areas = PeakShaveTools.cumulative_peak_areas(sorted_arr)
        index = PeakShaveTools.peak_area_idx(
            peak_areas,
            self.equipment.available_energy
        )
        return np.flip(sorted_arr)[index]

    def charge_threshold_proposal(self, dt: datetime):
        self.forecaster.window = self.charge_conditions.forecast_window
        forecast = self.forecaster.look_ahead(
            self.meter.tseries,
            dt
        )
        inverted_arr =\
            forecast[self.dispatch_on].values.max() \
            - forecast[self.dispatch_on].values
        return forecast[self.dispatch_on].values.max() \
            - TOUShiftingCalculator.calculate_proposal(
            inverted_arr,
            self.equipment.available_storage
        )

    def discharge_threshold_proposal(self, dt: datetime):
        self.forecaster.window = self.discharge_conditions.forecast_window
        forecast = self.forecaster.look_ahead(
            self.meter.tseries,
            dt
        )
        demand_arr = forecast[self.dispatch_on].values
        return TOUShiftingCalculator.calculate_proposal(
            demand_arr,
            self.equipment.available_energy
        )

    def set_threshold(
            self,
            dt: datetime,
    ):
        proposal = self.dispatch_threshold.value
        if self.threshold_schedule.charge_threshold.event_due(dt):
            proposal = self.charge_threshold_proposal(dt)
        if self.threshold_schedule.discharge_threshold.event_due(dt):
            proposal = self.discharge_threshold_proposal(dt)
        self.dispatch_threshold.set_threshold(proposal, dt)


@dataclass
class ThermalStorageController(StorageController):
    equipment: ThermalStorage = None
    meter: ThermalLoadFlexMeter = None
    dispatch_on: str = 'equivalent_thermal_energy'

    def set_threshold(
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
        proposed_threshold = PeakShaveTools.sub_load_peak_shave_limit(
            forecast,
            limiting_threshold_idx,
            self.equipment.available_energy,
            'gross_mixed_electrical_thermal',
            'equivalent_thermal_energy'
        )
        self.dispatch_threshold.set_threshold(proposed_threshold)
