import datetime
from abc import ABC, abstractmethod

from dataclasses import dataclass, field

from dispatch_control.constraints import DispatchConstraints
from dispatch_control.controllers import ParamController
from dispatch_control.dispatch_schedulers import DispatchConstraintSchedule
from dispatch_control.setpoints import DemandScenario
from equipment.equipment import Equipment, Dispatch
from metering import DispatchFlexMeter


@dataclass
class Dispatcher(ABC):
    name: str
    equipment: Equipment
    dispatch_constraint_schedule: DispatchConstraintSchedule
    special_constraints: DispatchConstraints
    meter: DispatchFlexMeter
    controller: ParamController
    dispatch_on: str

    historical_peak_demand: float = field(init=False, default=0.0)
    historical_min_demand: float = field(init=False, default=0.0)

    def __post_init__(self):
        self._parent_post_init()

    def _parent_post_init(self):
        """ Convenience method for preventing override of base class __post_init__

        Where child classes overide the __post_init__ method, they should call this method
        to ensure parent post init operations occur
        """
        pass

    @abstractmethod
    def optimise_dispatch_params(
            self,
            dt: datetime,
    ):
        """
        """
        pass

    @abstractmethod
    def dispatch(self):
        pass

    def add_setpoint_set_event(
            self,
            charge_params_dt: datetime = None,
            discharge_params_dt: datetime = None,
            universal_params_dt: datetime = None,
    ):
        self.controller.setpoints.add_setter_events(
            charge_params_dt,
            discharge_params_dt,
            universal_params_dt,
        )

    def demand_at_t(self, dt: datetime):
        return self.meter.tseries.loc[dt][self.dispatch_on]

    def setpoint_dispatch_proposal(self, demand_scenario: DemandScenario) -> Dispatch:
        return self.controller.setpoints.dispatch_proposal(
            demand_scenario,
            self.dispatch_constraint_schedule
        )

    def scheduled_dispatch_proposal(self, dt: datetime) -> Dispatch:
        return self.controller.dispatch_schedule.dispatch_proposal(dt)

    def apply_special_constraints(self, proposal: Dispatch) -> Dispatch:
        return self.special_constraints.constrain(proposal)

    def update_historical_net_demand(self, net_demand: float):
        self.historical_peak_demand = max(net_demand, self.historical_peak_demand)
        self.historical_min_demand = min(net_demand, self.historical_peak_demand)

    def report_dispatch(self, dt: datetime, dispatch: Dispatch):
        self.meter.update_dispatch(
            dt,
            dispatch,
            self.dispatch_on,
            {**self.controller.reportables, **self.equipment.status()}
        )

    def commit_dispatch(self, dt: datetime, dispatch: Dispatch, demand: float):
        self.dispatch_constraint_schedule.validate_dispatch(dispatch, dt)
        self.report_dispatch(dt, dispatch)
        self.update_historical_net_demand(demand - dispatch.net_value)
