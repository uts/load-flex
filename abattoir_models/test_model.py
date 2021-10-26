from datetime import timedelta, datetime
import pandas as pd

from portfolio.utils.data_utils import s3BucketManager, CacheManager
import os

from ts_tariffs.sites import Site, Meters
from ts_tariffs.tariffs import TariffRegime

from controllers import (
    SimpleBatteryPeakShaveController,
    HoursConstraint,
    PeakShaveDispatchThreshold,
    PeakShaveTOUDispatchThreshold,
    ExplicitCapsThreshold, ThresholdConditions, TouController, TwinScheduler
)
from local_data.local_data import aws_credentials, project_root
from metering import PowerFlexMeter

from storage import Battery
from time_series_utils import PerfectForcaster, Schedule, SpecificEvents, PeriodicEvents, SpecificHourEvents

from matplotlib import pyplot as plt


pd.options.display.float_format = '{:20,.2f}'.format


bucket_str = 'race-abattoir-load-flex'
cache_folder = os.path.join(project_root, '../local_data/s3_caching')

ab_project_folder = 'C:/Users/114261/Dropbox (UTS ISF)/1. 2021 Projects/21090_RACE_RACE Abattoirs - Fast Track/4. Work in progress/'

cache_manager = CacheManager(
    cache_folder,
    expiration=60 * 60 * 24,
    # expiration=1,
)

bucket_manager = s3BucketManager(
    bucket_str,
    aws_credentials['id'],
    aws_credentials['access_key'],
    cache_manager
)
jbs_folder = ['jbs_data']
jbs_tariff_regime_data = bucket_manager.s3_json_to_dict(
    jbs_folder,
    'jbs_tariff_structure.json'
)

jbs_consump_df = bucket_manager.s3_ftr_to_df(
    ['jbs_data'],
    'electricity_meter.ftr'
)

jbs_consump_df['demand_power'] = jbs_consump_df['Demand (KVA)'] * jbs_consump_df['Power Factor']


column_map = {
    'demand_energy': {
        'ts': 'Consumption (kWh)',
        'units': 'kWh'
    },
    'demand_apparent': {
        'ts': 'Demand (KVA)',
        'units': 'kVa'
    },
    'demand_power': {
        'ts': 'demand_power',
        'units': 'kW'
    },
    'power_factor': {
        'ts': 'Power Factor',
        'units': None
    },
    'generation_energy': {
        'ts': 'Generation (kWh)',
        'units': 'kWh'
        }
}

jbs_consump_df.set_index('datetime', inplace=True)
jbs_consump_df = jbs_consump_df.loc['2021-07-01': '2021-07-31']
meter = PowerFlexMeter.from_dataframe(
    'JBS',
    jbs_consump_df,
    timedelta(minutes=30),
    column_map
)
meters = Meters({meter.name: meter})
jbs_tariff_regime = TariffRegime(jbs_tariff_regime_data)
site = Site(
    'JBS',
    jbs_tariff_regime,
    meters,
)

forecaster = PerfectForcaster(timedelta(hours=24))
first_threshold_set_times = SpecificEvents(tuple([meter.first_datetime()]))
daily_charge_threshold_set_times = SpecificHourEvents(
    hours=tuple([22]),
    all_days=True
)
daily_discharge_threshold_set_times = SpecificHourEvents(
    hours=tuple([7]),
    all_days=True
)

charge_schedule = Schedule([first_threshold_set_times, daily_charge_threshold_set_times])
discharge_schedule = Schedule([daily_discharge_threshold_set_times])
scheduler = TwinScheduler(
    charge_schedule,
    discharge_schedule
)

battery = Battery(
    'battery',
    2000,
    2000,
    40_000,
    1.0,
    state_of_charge=1.0,
)

charge_hours = tuple((*range(0, 7), *range(22, 24)))
discharge_hours = tuple(range(7, 22))

charge_conds = ThresholdConditions(
    charge_hours,
    meter.max('demand_energy'),
    forecast_window=timedelta(hours=len(charge_hours))
)
discharge_conds = ThresholdConditions(
    discharge_hours,
    cap=None,
    forecast_window=timedelta(hours=len(discharge_hours))
)

threshold = PeakShaveTOUDispatchThreshold(
    0.0,
    0.0,
)

controller = TouController(
    'battery controller',
    battery,
    forecaster,
    scheduler,
    [],
    meter,
    dispatch_on='demand_energy',
    dispatch_threshold=threshold,
    charge_conditions=charge_conds,
    discharge_conditions=discharge_conds
)

controller.dispatch()
site.add_meter(
    meter.calculate_flexed_demand(
        'JBS_flexed',
        return_new_meter=True,
    )
)

fig, axs = plt.subplots(4, sharex=True)
axs[0].plot(site.meters['JBS'].dispatch_ts['dispatch_threshold'], color='gray', label='threshold')
axs[0].plot(site.meters['JBS'].tseries['demand_energy'], color='blue', label='base')
axs[0].plot(site.meters['JBS_flexed'].tseries['demand_energy'], color='green', label='flexed')
axs[1].plot(site.meters['JBS'].dispatch_ts['charge'], color='blue', label='charge')
axs[1].plot(site.meters['JBS'].dispatch_ts['discharge'], color='green', label='discharge')
axs[2].plot(site.meters['JBS'].dispatch_ts['cycle_count'], color='pink', label='cycle_count')
axs[3].plot(site.meters['JBS'].dispatch_ts['state_of_charge'], color='gray', label='state_of_charge')
axs[0].legend()
axs[1].legend()
axs[2].legend()
axs[3].legend()


plt.show()

print(site.meters['JBS_flexed'].tseries['demand_energy'].max())

site.calculate_bill()

baseline_bill = pd.Series(site.bills['JBS'].itemised_totals)
flexed_bill = pd.Series(site.bills['JBS_flexed'].itemised_totals)

print(baseline_bill)
print(flexed_bill)
comparison = baseline_bill.compare(flexed_bill, keep_shape=True)
print(comparison.diff(axis=1).round())





