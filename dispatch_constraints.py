from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Union, Tuple

from equipment import Dispatch
from time_series_utils import EventSchedule, PeriodSchedule


@dataclass
class DemandScenario:
    demand: float
    dt: datetime


@dataclass
class DispatchConstraint(ABC):
    @abstractmethod
    def limit_dispatch(
            self,
            demand_scenario: DemandScenario,
            proposal: Dispatch
    ) -> Dispatch:
        pass


# @dataclass
# class DemandChargeVsTouPeakConstraint(DispatchConstraint):
#     tou_tariff: TOUCharge
#     demand_tariff: DemandCharge
#     sample_rate: timedelta
#
#     @property
#     def demand_vs_tou_breakeven_point(self) -> float:
#         """ Breakeven point: The quantum of increased demand (as energy) in a
#         single timestep where the cost of the increase in the peak is equal to
#         the savings from TOU shifting (peak to offpeak) is equivalent
#
#         Answers the question: When is it cost effective to increase peak demand during
#         offpeak times for the sake of TOU load shifting?
#
#         * NOT A VERY SMART OPTIMISER:
#          - Assumes energy used to charge in offpeak is always discharged as peak tou
#          - assumes non-tou based demand charge
#         """
#         tou_shift_savings = \
#             max(self.tou_tariff.tou.bin_rates) - min(self.tou_tariff.tou.bin_rates)
#         sample_rate_hours = self.sample_rate / timedelta(hours=1)
#         return tou_shift_savings * sample_rate_hours / self.demand_tariff.rate
#
#     def limit_dispatch(
#             self,
#             demand_scenario: DemandScenario,
#             proposal: Dispatch
#     ) -> Dispatch:
#         """ Check if charging will increase peak for demand charge period - if yes, check if
#         it is economical to do so by calculating balance of TOU and demand tariffs. If not
#         economical, throttle charge rate to the point where it is economical
#         """
#         breach = max(
#             0.0,
#             demand_scenario.demand + proposal.charge - controller.setpoint.value
#         )
#         proposal.charge = min(self.demand_vs_tou_breakeven_point, breach)
#         return proposal


@dataclass
class DispatchSchedule:
    """ Defines hours when charging/discharging are permitted
    """
    charge_schedule: PeriodSchedule
    discharge_schedule: PeriodSchedule

    def charge(self, dt: datetime):
        return self.charge_schedule.period_active(dt)

    def discharge(self, dt: datetime):
        return self.discharge_schedule.period_active(dt)

    def both(self, dt: datetime):
        return self.charge(dt) and self.discharge(dt)

    def which_setpoint(self, dt: datetime) -> str:
        """ Identifies appropriate setpoint to use according to
        given datetime and the schedule
        """
        which = 'charge' if self.charge(dt) else 'universal'
        which = 'discharge'if self.discharge(dt) else which
        which = 'universal' if self.both(dt) else which
        return which

    def validate_dispatch(self, dispatch: Dispatch, dt: datetime):
        error_msg = 'Dispatch {} value must be zero outside {} schedule. ' \
                    'Error caught at datetime {}'.format
        dt_format = '%Y/%m/%d %H:%M'
        if dispatch.charge:
            if not self.charge(dt):
                raise ValueError(error_msg('charge', 'charge', dt.strftime(dt_format)))
        if dispatch.discharge:
            if not self.discharge(dt):
                raise ValueError(error_msg('discharge', 'discharge', dt.strftime(dt_format)))


@dataclass
class SetPointSchedule:
    """
    """
    charge: EventSchedule = None
    discharge: EventSchedule = None
    universal: EventSchedule = None

    def __post_init__(self):
        if not self.universal:
            self.universal = EventSchedule([])
        if not self.charge:
            self.charge = EventSchedule([])
        if not self.discharge:
            self.discharge = EventSchedule([])

    def universal_due(self, dt: datetime):
        return self.charge.event_due(dt)

    def charge_due(self, dt: datetime):
        return self.charge.event_due(dt)

    def discharge_due(self, dt: datetime):
        return self.discharge.event_due(dt)

    def event_due(self, dt: datetime):
        return self.charge_due(dt) \
               or self.discharge_due(dt) \
               or self.universal.event_due(dt)


@dataclass
class SetPointProposal:
    universal: Union[float, None] = None
    charge: Union[float, None] = None
    discharge: Union[float, None] = None


@dataclass
class SetPoint(ABC):
    schedule: SetPointSchedule
    charge_setpoint: float = field(init=False, default=0.0)
    discharge_setpoint: float = field(init=False, default=0.0)
    universal_setpoint: float = field(init=False, default=0.0)

    historical_peak_demand: float = field(init=False, default=0.0)
    historical_min_demand: float = field(init=False, default=0.0)

    def update_historical_net_demand(self, net_demand: float):
        self.historical_peak_demand = max(net_demand, self.historical_peak_demand)
        self.historical_min_demand = min(net_demand, self.historical_peak_demand)

    def charge_due(self, dt):
        return self.schedule.charge_due(dt)

    def discharge_due(self, dt):
        return self.schedule.discharge_due(dt)

    def universal_due(self, dt):
        return self.schedule.universal_due(dt)

    def raw_dispatch_proposal(
            self,
            demand_scenario: DemandScenario,
            schedule: DispatchSchedule
    ) -> float:
        """ Identify which setpoint to use and find difference against
        demand
        """
        setpoints = {
            'universal': demand_scenario.demand - self.universal_setpoint,
            'charge': min(0.0, demand_scenario.demand - self.charge_setpoint),
            'discharge': max(0.0, demand_scenario.demand -self.discharge_setpoint),
        }
        x =schedule.which_setpoint(demand_scenario.dt)
        return setpoints[schedule.which_setpoint(demand_scenario.dt)]

    @abstractmethod
    def set(
            self,
            proposal: SetPointProposal,
            dt: datetime = None
    ):
        pass


@dataclass
class PeakShaveSetPoint(SetPoint):
    def set(
            self,
            proposal: SetPointProposal,
            dt: datetime = None
    ):
        """ Adjusts universal setpoint according to proposal and historical maximum.

        This strategy reduces the depth of peak shaving attempted by limiting it
        to be only as good as historical achievement. This is specifically advantageous
        where demand tariffs are the primary concern and there is no advantage in peak shaving
        below the period's peak demand. The advantage is gained by reducing the available
        energy required to achieve the target peak - i.e. there is more likelihood of energy
        being available
        """
        if proposal:
            self.universal_setpoint = max(
                proposal.universal,
                self.historical_peak_demand
            )


@dataclass
class GenericSetPoint(SetPoint):
    def set(
            self,
            proposal: SetPointProposal,
            dt: datetime = None
    ):
        """ Accepts whatever setpoints are proposed
        """
        if proposal.charge:
            self.charge_setpoint = proposal.charge
        if proposal.discharge:
            self.discharge_setpoint = proposal.discharge
        if proposal.universal:
            self.universal_setpoint = proposal.universal


@dataclass
class SetPointCap:
    hours: Tuple[int]
    cap: float


# @dataclass
# class CappedSetPoint(SetPoint):
#     charge_cap: SetPointCap = None
#     discharge_cap: SetPointCap = None
#     universal_cap: SetPointCap = None
#
#     def set(
#             self,
#             proposal: SetPointProposal,
#             dt: datetime = None
#     ):
#         if self.charge_cap:
#             if dt.hour in self.charge_cap.hours:
#                 self.charge_setpoint = self.charge_cap.cap
#         if self.discharge_cap:
#             if dt.hour in self.discharge_cap.hours:
#                 self.charge_setpoint = self.discharge_cap.cap
#         if self.discharge_cap:
#             if dt.hour in self.universal_cap.hours:
#                 self.universal_setpoint = self.universal_cap.cap
