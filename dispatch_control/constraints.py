from abc import ABC, abstractmethod
from dataclasses import dataclass

from dispatch_control.setpoints import DemandScenario
from equipment import Dispatch


@dataclass
class DispatchConstraint(ABC):
    @abstractmethod
    def constrain_dispatch(
            self,
            demand_scenario: DemandScenario,
            proposal: Dispatch,
    ) -> Dispatch:
        pass
