from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import timedelta, datetime

from equipment.equipment import Dispatch
from time_tools.schedulers import DailyPeriod, Period, EventSchedule, DateRangePeriod


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
    compressor_electrical_capacity: float
    baseline_cop: float
    high_pressure_cop: float
    repayment_schedule: EventSchedule
    energy_to_repay: float = 0.0
    extended_cycle_dispatch: DispatchBlock = field(init=False)

    @property
    def repayment_duration(self) -> timedelta:
        return timedelta(
            hours=self.energy_to_repay / self.compressor_electrical_capacity
        )

    @property
    def load_diff_proportion(self):
        """ Proportion of decrease in electrical demand based on higher suction pressure due to
        cop increase

        Therefore, effective electrical dispatch = load_reduction_proportion * electrical demand
        """
        return 1.0 - self.baseline_cop / self.high_pressure_cop

    def update_energy_repayment(self, dt: datetime):
        """
        """
        self.extended_cycle_dispatch = DispatchBlock(
            self.compressor_electrical_capacity,
            0.0,
            DateRangePeriod(
                dt,
                dt + self.repayment_duration
            )
        )

    def apply_setting(self, demand: float) -> Dispatch:
        demand_reduction = demand * self.load_diff_proportion
        return Dispatch.from_raw_float(demand_reduction)

    def update_energy_to_repay(
            self,
            dispatch: Dispatch,
    ):
        self.energy_to_repay += dispatch.net_value

    def repay_energy(self, dt: datetime):
        if self.extended_cycle_dispatch.dispatch_period.period_active(dt):
            return self.extended_cycle_dispatch
        else:
            Dispatch(0.0, 0.0)
