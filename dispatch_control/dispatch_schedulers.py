from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List

from dispatch_control.parameters import ParamSetterSchedules
from equipment.equipment import Dispatch, Storage
from time_series_tools.schedulers import PeriodSchedule, Period


@dataclass
class EquipmentDispatchSchedule:
    """ Schedule for charging and discharging at specific rates
    """
    setter_schedule: ParamSetterSchedules
    charge_schedule: PeriodSchedule
    discharge_schedule: PeriodSchedule
    equipment: Storage

    @property
    def charge_rate(self):
        return self.equipment.charge_capacity

    @property
    def discharge_rate(self):
        return self.equipment.discharge_capacity

    def scheduled_charge(self, dt: datetime):
        if self.charge_schedule.period_active(dt):
            return self.charge_rate
        else:
            return 0.0

    def scheduled_discharge(self, dt: datetime):
        if self.discharge_schedule.period_active(dt):
            return self.discharge_rate
        else:
            return 0.0

    def dispatch_proposal(self, dt, sample_rate: timedelta) -> Dispatch:
        sample_rate_hours = sample_rate / timedelta(hours=1)
        return Dispatch(
            charge=self.scheduled_charge(dt) * sample_rate_hours,
            discharge=self.scheduled_discharge(dt) * sample_rate_hours
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

    def clear_schedule(self):
        self.charge_schedule.clear_schedule()
        self.discharge_schedule.clear_schedule()

    @classmethod
    def empty_schedule(cls, equipment: Storage):
        return cls(
            ParamSetterSchedules(),
            PeriodSchedule(),
            PeriodSchedule(),
            equipment
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
