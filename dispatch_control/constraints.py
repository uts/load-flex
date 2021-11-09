from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List

from dispatch_control.setpoints import DemandScenario
from equipment import Dispatch


@dataclass
class DispatchConstraint(ABC):
    @abstractmethod
    def constrain(
            self,
            proposal: Dispatch,
    ) -> Dispatch:
        pass


@dataclass
class DispatchConstraints:
    constraints: List[DispatchConstraint] = None

    def __post_init__(self):
        if not self.constraints:
            self.constraints = []

    def constrain(self, proposal: Dispatch):
        for constraint in self.constraints:
            proposal = constraint.constrain(proposal)
        return proposal
