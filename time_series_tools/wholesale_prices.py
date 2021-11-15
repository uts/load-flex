import datetime
from dataclasses import dataclass

import pandas as pd
import numpy as np
from scipy.signal import find_peaks

from ts_tariffs.sites import MeterData

from time_series_tools.forecasters import Forecaster
from validators import Validator

MARKET_PRICE_COLS = ('price', )


@dataclass
class DispatchPairs:
    pass


@dataclass
class TurningPoints:
    type: str
    indices: np.ndarray
    values: np.ndarray

    def __post_init__(self):
        if self.type not in ['minima', ',maxima']:
            raise ValueError('TurningPoints type attr must be "minima" or "maxima"')

    def sorted_by_value(self):
        order = self.values.argsort()
        return TurningPoints(self.type, self.indices[order], self.values[order])


@dataclass
class TurningPointPairs:
    peaks: TurningPoints
    troughs: TurningPoints

    def dispatch_pairs(self, number_of_pairs):
        return


@dataclass
class MarketPrices(MeterData):
    forecaster: Forecaster

    def __post_init__(self):
        Validator.data_cols(self.tseries, MARKET_PRICE_COLS)

    def forecast_turning_point_pairs(self, dt: datetime):
        forecast = self.forecaster.look_ahead(self.tseries, dt)
        peaks = find_peaks(forecast['price'], height=0.0)
        troughs = find_peaks(-forecast['price'], height=0.0)
        troughs[1]['peak_heights'] *= -1.0
        return TurningPointPairs(
            TurningPoints('maxima', peaks[0], peaks[1]['peak_heights']),
            TurningPoints('troughs', troughs[0], troughs[1]['peak_heights'])
        )

    def forecast(self, dt: datetime):
        return self.forecaster.look_ahead(self.tseries, dt)

    def calculate_ts_bill(self, consumption: MeterData, consumption_col: str):
        bill = pd.concat([self.tseries, consumption.tseries[consumption_col]], axis=1)
        bill['energy_cost'] = bill['price'] * bill[consumption_col]
        return bill

    def calculate_bill_total(self, consumption: MeterData, consumption_col: str):
        bill = self.calculate_ts_bill(consumption, consumption_col)
        return bill['energy_cost'].sum(skipna=True)
