import pandas as pd
from datetime import timedelta, datetime
from matplotlib import pyplot as plt

from controllers import Controller, SimpleBatteryController
from time_series_utils import PerfectForcaster, Scheduler
from equipment import Battery, Storage, Equipment, EquipmentMetadata


demand = pd.read_csv('https://solar-gardens.s3.ap-southeast-2.amazonaws.com/profiles/blacktown_bus_5_day.csv')
demand['datetime'] = pd.to_datetime(demand['datetime'], format='%d/%m/%Y %H:%M')
demand.set_index('datetime', inplace=True)
demand_arr = demand['consumption'] * 10000

controller = SimpleBatteryController()
battery_metadata = EquipmentMetadata('Test', 10000, 200)
forecaster = PerfectForcaster(timedelta(hours=24))
scheduler = Scheduler(
    start_dt=datetime(2014, 7, 1, 0),
    interval=timedelta(hours=24)
)
battery = Battery(
    battery_metadata,
    10,
    10,
    20,
    1.0,
    1.0,
    pd.DataFrame()
)

controller.dispatch(
    demand_arr,
    forecaster,
    battery,
    scheduler,
)

print(max(controller.dispatch_report['net_demand']))
print(controller.dispatch_report)

plt.stackplot(
    controller.dispatch_report.index,
    controller.dispatch_report['net_demand'],
    # controller.dispatch_report['battery_charge'],
    # controller.dispatch_report['battery_discharge'],
    labels=[
        'net_demand',
        'battery_charge',
        'battery_discharge'
    ]
)
plt.plot(
    controller.dispatch_report.index,
    controller.dispatch_report['demand'],
    label='demand'
)
plt.plot(
    controller.dispatch_report.index,
    controller.dispatch_report['battery_soc'],
    label='battery_soc'
)
plt.plot(
    controller.dispatch_report.index,
    controller.dispatch_report['peak_threshold'],
    label='peak_threshold'
)

plt.legend()
plt.show()

