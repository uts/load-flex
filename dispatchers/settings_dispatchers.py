from dataclasses import dataclass
from datetime import datetime

from dispatchers.dispatchers import Dispatcher
from equipment.settings_adjustments import CompressorSuctionPressure


@dataclass
class SettingsDispatcher(Dispatcher):
    setting: CompressorSuctionPressure

    def __post_init__(self):
        self._parent_post_init()

    def optimise_dispatch_params(
            self,
            dt: datetime,
    ):
        """ Update setpoints for gross curve load shifting
        """
        pass

    def dispatch(self):
        for dt, demand in self.meter.tseries.iterrows():
            dispatch = self.setting.apply_setting(demand[self.dispatch_on])
            self.setting.update_energy_to_repay(dispatch)
            if dispatch.no_dispatch:
                dispatch = self.setting.repay_energy(dt)
                self.setting.update_energy_repayment(dispatch)
            self.commit_dispatch(dt, dispatch, demand[self.dispatch_on])
