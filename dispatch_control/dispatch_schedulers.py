from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List

from dispatch_control.parameters import ParamSetterSchedules
from equipment.equipment import Dispatch
from time_series_tools.schedulers import PeriodSchedule, Period


@dataclass
class DispatchSchedule:
    """ Schedule for charging and discharging at specific rates
    """
    setter_schedule: ParamSetterSchedules
    charge_schedule: PeriodSchedule
    discharge_schedule: PeriodSchedule
    charge_energy: float = None
    discharge_energy: float = None

    def scheduled_charge(self, dt: datetime):
        if self.charge_schedule.period_active(dt):
            return self.charge_energy
        else:
            return 0.0

    def scheduled_discharge(self, dt: datetime):
        if self.discharge_schedule.period_active(dt):
            return self.discharge_energy
        else:
            return 0.0

    def dispatch_proposal(self, dt) -> Dispatch:
        return Dispatch(
            charge=self.scheduled_charge(dt),
            discharge=self.scheduled_discharge(dt)
        )

    def append_schedule(
            self,
            charge_periods: List[Period] = None,
            discharge_periods: List[Period] = None
    ):
        if charge_periods:
            self.charge_schedule.add_periods(charge_periods)
        if discharge_periods:
            self.discharge_schedule.add_periods(discharge_periods)

    @classmethod
    def empty_schedule(cls):
        return cls(
            ParamSetterSchedules(),
            PeriodSchedule(),
            PeriodSchedule(),
        )


@dataclass
class DispatchConstraintSchedule:
    """ Constrains when and how much dispatch is allowed at
    specific times
    """
    no_charge_period: PeriodSchedule
    no_discharge_period: PeriodSchedule
    absolute_charge_limit: float = None
    absolute_discharge_limit: float = None
    allow_non_scheduled_dispatch: bool = False

    def __post_init__(self):
        if not self.absolute_charge_limit:
            self.absolute_charge_limit = float('inf')
        if not self.absolute_discharge_limit:
            self.absolute_discharge_limit = float('inf')

    def allowable_charge(self, dt: datetime) -> float:
        allowable_charge = self.absolute_charge_limit
        if self.no_charge_period.period_active(dt):
            allowable_charge = 0.0
        return allowable_charge

    def allowable_discharge(self, dt: datetime):
        allowable_discharge = self.absolute_discharge_limit
        if self.no_discharge_period.period_active(dt):
            allowable_discharge = 0.0
        return allowable_discharge

    def all_dispatch_allowed(self, dt: datetime):
        return self.allowable_charge(dt) and self.allowable_discharge(dt)

    def which_setpoint(self, dt: datetime) -> str:
        """ Identifies appropriate setpoint to use according to
        given datetime and the schedule
        """
        which = 'charge' if self.allowable_charge(dt) else 'None'
        which = 'discharge'if self.allowable_discharge(dt) else which
        which = 'universal' if self.all_dispatch_allowed(dt) else which
        return which

    def validate_dispatch(self, dispatch: Dispatch, dt: datetime):
        if not self.allow_non_scheduled_dispatch:
            error_msg = 'Dispatch {} value must be zero outside {} schedule. ' \
                        'Error caught at datetime {}'.format
            dt_format = '%Y/%m/%d %H:%M'
            if dispatch.charge:
                if not self.allowable_charge(dt):
                    raise ValueError(error_msg('charge', 'charge', dt.strftime(dt_format)))
            if dispatch.discharge:
                if not self.allowable_discharge(dt):
                    raise ValueError(error_msg('discharge', 'discharge', dt.strftime(dt_format)))

    @classmethod
    def empty_schedule(cls):
        return cls(PeriodSchedule([]), PeriodSchedule([]))
