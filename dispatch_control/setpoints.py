from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Union, Tuple
import pandas as pd

from dispatch_control.dispatch_schedulers import AllowableDispatchSchedule
from dispatch_control.parameters import ParamSetterSchedule
from equipment import Dispatch
from time_tools.forecasters import PerfectForcaster
from time_tools.schedulers import SpecificEvents


@dataclass
class SetpointForecasters:
    """ Specification of different forecasting
    params for charge, discharge and universal
    setpoint calcs
    """
    charge: PerfectForcaster
    discharge: PerfectForcaster
    universal: PerfectForcaster

    @classmethod
    def from_hours(cls, charge, discharge, universal):
        """ Instantiate SetpointForecasters object given
        forecast windows for charge, discharge and universal
        setpoint in terms of hours
        """
        return cls(
            PerfectForcaster(timedelta(hours=charge)),
            PerfectForcaster(timedelta(hours=discharge)),
            PerfectForcaster(timedelta(hours=universal))
        )


@dataclass
class DemandScenario:
    demand: float
    dt: datetime
    balance_energy: float


@dataclass
class SetPointProposal:
    universal: Union[float, None] = None
    charge: Union[float, None] = None
    discharge: Union[float, None] = None


@dataclass
class SetPoints:
    setter_schedule: ParamSetterSchedule
    forecasters: SetpointForecasters
    charge_setpoint: float = field(init=False, default=0.0)
    discharge_setpoint: float = field(init=False, default=0.0)
    universal_setpoint: float = field(init=False, default=0.0)

    def charge_due(self, dt):
        return self.setter_schedule.charge_params_due(dt)

    def discharge_due(self, dt):
        return self.setter_schedule.discharge_params_due(dt)

    def universal_due(self, dt):
        return self.setter_schedule.universal_params_due(dt)

    def dispatch_proposal(
            self,
            demand_scenario: DemandScenario,
            schedule: AllowableDispatchSchedule
    ) -> Dispatch:
        """ Identify which setpoint is relevant for dt and propose a dispatch
        """
        potential_dispatches = {
            'universal': demand_scenario.demand - self.universal_setpoint,
            'charge': min(0.0, demand_scenario.demand - self.charge_setpoint),
            'discharge': max(0.0, demand_scenario.demand - self.discharge_setpoint),
            'None': 0.0
        }
        raw_proposal = potential_dispatches[schedule.which_setpoint(demand_scenario.dt)]
        return Dispatch.from_raw_float(raw_proposal)

    def add_setter_events(
            self,
            charge_params_dt: datetime = None,
            discharge_params_dt: datetime = None,
            universal_params_dt: datetime = None,
    ):
        if charge_params_dt:
            self.setter_schedule.charge_params.add_event(SpecificEvents(tuple([charge_params_dt])))
        if discharge_params_dt:
            self.setter_schedule.discharge_params.add_event(SpecificEvents(tuple([discharge_params_dt])))
        if universal_params_dt:
            self.setter_schedule.universal_params.add_event(SpecificEvents(tuple([universal_params_dt])))

    def universal_forecast(
            self,
            tseries: pd.DataFrame,
            start_dt: datetime
    ):
        return self.forecasters.universal.look_ahead(
            tseries, start_dt
        )

    def charge_forecast(
            self,
            tseries: pd.DataFrame,
            start_dt: datetime
    ):
        return self.forecasters.charge.look_ahead(
            tseries, start_dt
        )

    def discharge_forecast(
            self,
            tseries: pd.DataFrame,
            start_dt: datetime
    ):
        return self.forecasters.discharge.look_ahead(
            tseries, start_dt
        )


    def set_setpoints(
            self,
            setpoint_proposal: SetPointProposal,
            dt: datetime = None
    ):
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


@dataclass
class CappedSetPoints(SetPoints):
    charge_cap: SetPointCap = None
    discharge_cap: SetPointCap = None
    universal_cap: SetPointCap = None

    def set_setpoints(
            self,
            proposal: SetPointProposal,
            dt: datetime = None
    ):
        if self.charge_cap:
            if dt.hour in self.charge_cap.hours:
                self.charge_setpoint = self.charge_cap.cap
        if self.discharge_cap:
            if dt.hour in self.discharge_cap.hours:
                self.charge_setpoint = self.discharge_cap.cap
        if self.discharge_cap:
            if dt.hour in self.universal_cap.hours:
                self.universal_setpoint = self.universal_cap.cap
