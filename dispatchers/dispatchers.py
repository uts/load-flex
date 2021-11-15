import datetime
from abc import ABC, abstractmethod

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from dispatch_control.constraints import DispatchConstraints
from dispatch_control.controllers import ParamController
from dispatch_control.dispatch_schedulers import DispatchConstraintSchedule
from dispatch_control.setpoints import DemandScenario
from equipment.equipment import Equipment, Dispatch, Storage
from time_series_tools.metering import DispatchFlexMeter
from time_series_tools.wholesale_prices import MarketPrices

from time import time


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
        demand = self.demand_at_t(dt)
        proposal = self.controller.primary_dispatch_schedule.dispatch_proposal(
            dt,
            self.meter.sample_rate
        )
        proposal.discharge = min(demand, proposal.discharge)
        return proposal

    def scheduled_secondary_dispatch_proposal(self, dt: datetime) -> Dispatch:
        return self.controller.secondary_dispatch_schedule.dispatch_proposal(
            dt,
            self.meter.sample_rate
        )

    def apply_special_constraints(self, proposal: Dispatch) -> Dispatch:
        return self.special_constraints.constrain(proposal)

    def update_historical_net_demand(self, net_demand: float):
        self.historical_peak_demand = max(net_demand, self.historical_peak_demand)
        self.historical_min_demand = min(net_demand, self.historical_peak_demand)

    def report_dispatch(self, dt: datetime, dispatch: Dispatch):
        self.meter.update_dispatch(
            dt,
            dispatch,
            {**self.controller.reportables, **self.equipment.status()}
        )

    def commit_dispatch(self, dt: datetime, dispatch: Dispatch, demand: float):
        self.dispatch_constraint_schedule.validate_dispatch(dispatch, dt)
        self.report_dispatch(dt, dispatch)
        self.update_historical_net_demand(demand - dispatch.net_value)


@dataclass
class StorageDispatcher(Dispatcher):
    equipment: Storage

    def __post_init__(self):
        self._parent_post_init()

    @abstractmethod
    def optimise_dispatch_params(
            self,
            dt: datetime,
    ):
        """ Update setpoints for gross curve load shifting
        """
        pass

    def dispatch(self):
        self.meter.set_reportables(
            {**self.controller.reportables, **self.equipment.status()}.keys()
        )
        for dt, demand in self.meter.tseries.iterrows():
            self.optimise_dispatch_params(dt)

            # Only invoke setpoints if no scheduled dispatch
            dispatch_proposal = self.scheduled_dispatch_proposal(dt)
            if self.controller.secondary_dispatch_schedule:
                if dispatch_proposal.no_dispatch:
                    dispatch_proposal = self.scheduled_secondary_dispatch_proposal(dt)
            if self.controller.setpoints:
                if dispatch_proposal.no_dispatch:
                    demand_scenario = DemandScenario(
                        demand[self.dispatch_on],
                        dt,
                        self.meter.tseries['balance_energy'].loc[dt]
                    )
                    dispatch_proposal = self.setpoint_dispatch_proposal(demand_scenario)
            dispatch_proposal = self.apply_special_constraints(dispatch_proposal)
            dispatch_proposal.validate()
            dispatch = self.equipment.dispatch_request(dispatch_proposal, self.meter.sample_rate)
            self.commit_dispatch(dt, dispatch, demand[self.dispatch_on])
        self.meter.consolidate_updates(self.dispatch_on)


@dataclass
class WholesalePriceTranchDispatcher(StorageDispatcher):
    market_prices: MarketPrices
    forecast_resolution: timedelta = timedelta(hours=0.5)
    tranche_energy: float = field(init=False)
    number_tranches: int = field(init=False)

    def __post_init__(self):
        self._parent_post_init()
        self.calculate_tranches()
        # self.initialise_setpoint(self.meter.first_datetime())

    def calculate_tranches(self):
        """Tranches defined by how much energy can be dispatched in a single time step as per the
        forecast resolution and how much storage capacity the battery has (assume smallest
        of charge or discharge rates)
        """
        time_step_hours = self.forecast_resolution / timedelta(hours=1)
        dispatch_rate = min(
            self.equipment.nominal_charge_capacity,
            self.equipment.nominal_discharge_capacity
        )

        self.tranche_energy = dispatch_rate * time_step_hours
        # Need positive number of whole tranches as they will be allocated
        # equally to charge and discharge - this will leave remainder unallocated
        self.number_tranches = int(self.equipment.storage_capacity / self.tranche_energy)
        if self.number_tranches % 2 != 0:
            self.number_tranches -= 1

    @abstractmethod
    def set_dispatch_schedule(self, dt):
        pass

    @abstractmethod
    def optimise_dispatch_params(
            self,
            dt: datetime,
    ):
        """ Update setpoints for gross curve load shifting
        """
        pass