from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Union, Tuple, List
import  pandas as pd
from ts_tariffs.tariffs import TOUCharge, DemandCharge

from equipment import Dispatch
from time_series_utils import EventSchedule, PeriodSchedule


@dataclass
class DemandScenario:
    demand: float
    dt: datetime
    setpoint: SetPoint


@dataclass
class DispatchConstraint(ABC):
    @abstractmethod
    def limit_dispatch(
            self,
            demand_scenario: DemandScenario,
            proposal: Dispatch,
    ) -> Dispatch:
        pass


@dataclass
class DispatchSchedule:
    """ Defines hours when charging/discharging are permitted
    """
    charge_schedule: PeriodSchedule
    discharge_schedule: PeriodSchedule
    charge_constraints: pd.Series = None
    discharge_constraints: pd.Series = None
    allow_non_scheduled_dispatch: bool = False

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
        which = 'charge' if self.charge(dt) else 'None'
        which = 'discharge'if self.discharge(dt) else which
        which = 'universal' if self.both(dt) else which
        return which

    def validate_dispatch(self, dispatch: Dispatch, dt: datetime):
        if not self.allow_non_scheduled_dispatch:
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
    pause_setpoints: PeriodSchedule = None

    def __post_init__(self):
        if not self.universal:
            self.universal = EventSchedule([])
        if not self.charge:
            self.charge = EventSchedule([])
        if not self.discharge:
            self.discharge = EventSchedule([])

    def pause(self, dt: datetime) -> bool:
        return self.pause_setpoints.period_active(dt)

    def universal_due(self, dt: datetime) -> bool:
        return False if self.pause(dt) else self.universal.event_due(dt)

    def charge_due(self, dt: datetime)-> bool:
        return False if self.pause(dt) else self.charge.event_due(dt)

    def discharge_due(self, dt: datetime)-> bool:
        return False if self.pause(dt) else self.discharge.event_due(dt)

    def event_due(self, dt: datetime)-> bool:
        return self.charge_due(dt) \
               or self.discharge_due(dt) \
               or self.universal_due(dt)


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
        diffs = {
            'universal': demand_scenario.demand - self.universal_setpoint,
            'charge': min(0.0, demand_scenario.demand - self.charge_setpoint),
            'discharge': max(0.0, demand_scenario.demand -self.discharge_setpoint),
            'None': 0.0
        }
        return diffs[schedule.which_setpoint(demand_scenario.dt)]

    @abstractmethod
    def set(
            self,
            setpoint_proposal: SetPointProposal,
            dt: datetime = None
    ):
        pass


@dataclass
class PeakShaveSetPoint(SetPoint):
    def set(
            self,
            setpoint_proposal: SetPointProposal,
            dt: datetime = None
    ):
        """ Unconstrained peak shaving
        """
        if setpoint_proposal.universal:
            self.universal_setpoint = setpoint_proposal.universal


@dataclass
class ConservativePeakShaveSetPoint(SetPoint):
    def set(
            self,
            setpoint_proposal: SetPointProposal,
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
        if setpoint_proposal.universal:
            self.universal_setpoint = max(
                setpoint_proposal.universal,
                self.historical_peak_demand
            )


@dataclass
class TouPeakShaveComboSetPoint(SetPoint):
    def set(
            self,
            setpoint_proposal: SetPointProposal,
            dt: datetime = None
    ):
        """ Adjusts charge setpoint according to proposal and historical maximum.

        This strategy constrains charging to prevent increased peak demand
        """

        if setpoint_proposal.charge:
            self.charge_setpoint = min(
                setpoint_proposal.charge,
                self.historical_peak_demand
            )
        if setpoint_proposal.discharge:
            self.discharge_setpoint = setpoint_proposal.discharge



@dataclass
class GenericSetPoint(SetPoint):
    def set(
            self,
            setpoint_proposal: SetPointProposal,
            dt: datetime = None
    ):
        """ Accepts whatever setpoints are proposed
        """
        if setpoint_proposal.charge:
            self.charge_setpoint = setpoint_proposal.charge
        if setpoint_proposal.discharge:
            self.discharge_setpoint = setpoint_proposal.discharge
        if setpoint_proposal.universal:
            self.universal_setpoint = setpoint_proposal.universal


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
