from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import timedelta, datetime

from equipment.equipment import Dispatch
from time_series_tools.schedulers import DailyPeriod, Period, EventSchedule, DateRangePeriod


@dataclass
class Setting:
    @abstractmethod
    def apply_setting(self, demand: float) -> Dispatch:
        """ Returns effective electrical dispatch based on changed equipment settings.

        Effective dispatch is considered in terms of discharge and charge
        in the same way it would be in a battery where discharge replaces grid energy usage,
        and charge uses additional grid energy
        E.g.
         - if setting effect is to save 10% demand energy, the dispatch
        will be a discharge = 0.1 * demand
         - if setting effect is to use additional 10% demand energy, the
         dispatch will be charge = 0.1 * demand
        """
        pass

    @abstractmethod
    def repay_dispatch(self, demand: float) -> Dispatch:
        pass

@dataclass
class DispatchBlock(Dispatch):
    """ Specification of continuous Dispatch for a particular period of time
    """
    dispatch_period: Period


@dataclass
class CompressorSuctionPressure(Setting):
    """ Compressor low-side suction pressure variation affects COP. Increasing pressure
    reduces COP and reducing pressure decreases COP. Electrical load for a given thermal
    load changes accordingly with COP

    This does affect throughput and will change the cooling/freezing time required
    for a given cooling cycle
    """
    baseline_cop: float
    low_pressure_cop: float
    high_pressure_cop: float

    @property
    def high_pressure_load_factor(self):
        """ Proportion of decrease in electrical demand based on higher suction pressure due to
        cop increase

        Therefore, effective electrical dispatch = load_reduction_proportion * electrical demand
        """
        return 1.0 - self.baseline_cop / self.high_pressure_cop

    @property
    def low_pressure_load_factor(self):
        """ Proportion of increase in electrical demand based on lower suction pressure due to
        cop increase
        """
        return 1.0 - self.baseline_cop / self.low_pressure_cop

    def apply_setting(self, demand: float) -> Dispatch:
        delta_energy = demand * self.high_pressure_load_factor
        return Dispatch(charge=0.0, discharge=delta_energy)

    def repay_dispatch(self, demand: float) -> Dispatch:
        delta_energy = demand * self.low_pressure_load_factor
        return Dispatch(charge=-delta_energy, discharge=0.0)


@dataclass
class FanThrottle(Setting):
    """ Throttle fan speed and estimate power savings via fan affinity laws

    This does affect throughput and will change the cooling/freezing time required
    for a given cooling cycle
    """
    throttle_rate: float
    _last_borrowed_energy: float

    @staticmethod
    def power_consumption_ratio(throttle_rate):
        """ Ratio of P2 / P1 when fan speed is throttled at
        relative rate
        Based on fan affinity laws
        """
        return 1.0 / (1 / (1.0 - throttle_rate))**3

    def apply_setting(self, demand: float) -> Dispatch:
        delta_energy = demand * (1 - self.power_consumption_ratio(self.throttle_rate))
        self._last_borrowed_energy = delta_energy
        return Dispatch(charge=0.0, discharge=delta_energy)

    def repay_dispatch(self, demand: float) -> Dispatch:
        return Dispatch(charge=self._last_borrowed_energy, discharge=0.0)
