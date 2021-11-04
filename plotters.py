from dataclasses import dataclass, field
from datetime import datetime
from typing import Union
import seaborn as sns
from matplotlib import pyplot as plt
import pandas as pd

WEEKDAY_DAYS = [0, 1, 2, 3, 4]
sns.set_theme(style="whitegrid")


@dataclass
class PlotMeters:
    base_tseries: pd.DataFrame
    flexed_tseries: pd.DataFrame
    palette: Union[str, dict]
    categorical_combined_data: pd.DataFrame = field(init=False)

    def __post_init__(self):
        self.add_time_cols(self.flexed_tseries)
        self.flexed_tseries['Before/After Flexing'] = 'After'
        self.add_time_cols(self.base_tseries)
        self.base_tseries['Before/After Flexing'] = 'Before'
        self.combine_meters()

    @staticmethod
    def add_time_cols(meter):
        meter['time'] = meter.index.time
        meter['weekday'] = meter.index.dayofweek.isin(WEEKDAY_DAYS)
        meter['datetime'] = meter.index
        meter['datetime_str'] = meter['datetime'].apply(lambda x: x.strftime('%Y-%m-%d %H:%M:%S'))

    def combine_meters(self):
        flexed_df = self.flexed_tseries.copy()
        flexed_df.reset_index(inplace=True, drop=True)
        base_df = self.base_tseries.copy()
        base_df.reset_index(inplace=True, drop=True)
        self.categorical_combined_data = pd.concat(
            [flexed_df, base_df],
            axis=0
        )

    def box_plot(self, plot_col):
        sns.boxplot(
            x="time",
            y=plot_col,
            hue='Before/After Flexing',
            data=self.categorical_combined_data,
            showfliers=False,
            palette="Set3"
        )
        plt.xticks(rotation=-45)
        plt.show()


    def lineplot(self, plot_col):

        sns.relplot(
            data=self.categorical_combined_data,
            kind='line',
            x="time",
            y=plot_col,
            hue='flexed'
        )
        plt.show()
