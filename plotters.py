from dataclasses import dataclass, field, asdict
from typing import Union
import seaborn as sns
from matplotlib import pyplot as plt
import pandas as pd

WEEKDAY_DAYS = [0, 1, 2, 3, 4]
sns.set_theme(style="whitegrid")


@dataclass
class LabelConfig:
    fontsize: float
    color: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class TitleConfig(LabelConfig):
    label: str


@dataclass
class AxesConfig(LabelConfig):
    ylabel: str
    xlabel: str

    def configure_plot(self, p):
        p.se



@dataclass
class PlotConfig:
    axes: AxesConfig = None
    title: LabelConfig = None


@dataclass
class FlexPlotter:
    base_tseries: pd.DataFrame
    flexed_tseries: pd.DataFrame
    dispatch_tseries: pd.DataFrame
    palette: Union[str, dict, None]
    categorical_combined_data: pd.DataFrame = field(init=False)
    market_prices: pd.DataFrame = None

    def __post_init__(self):
        self.add_time_cols(self.flexed_tseries)
        self.flexed_tseries['Before/After Flexing'] = 'After'
        self.add_time_cols(self.base_tseries)
        self.base_tseries['Before/After Flexing'] = 'Before'
        self.combine_meters()
        self.add_time_cols(self.dispatch_tseries)
        self.add_time_cols(self.market_prices)

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

    @staticmethod
    def configure_plot(p, plot_config: PlotConfig):
        # TODO: genericise this to a loop
        if plot_config:
            if plot_config.axes:
                p.set_ylabel(**plot_config.axes.as_dict())
                p.set_xlabel(**plot_config.axes.as_dict())
            if plot_config.title:
                p.set_title(**plot_config.title.as_dict())

    def box_plot(
            self,
            data: str,
            plot_col: str,
            plot_config: PlotConfig = None,
            **kwargs
    ):
        plt_data = getattr(self, data)
        p = sns.boxplot(
            x="time",
            y=plot_col,
            data=plt_data,
            showfliers=False,
            **kwargs
        )
        self.configure_plot(p, plot_config)
        plt.xticks(rotation=-45)
        plt.show()

    def comparison_box_plot(self, plot_col, **kwargs):
        sns.boxplot(
            x="time",
            y=plot_col,
            hue='Before/After Flexing',
            data=self.categorical_combined_data,
            showfliers=False,
            palette="Set3",
            **kwargs
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
