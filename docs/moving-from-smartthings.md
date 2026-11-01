# Moving from the SmartThings integration

Home Assistant's built-in SmartThings integration reaches your appliances through Samsung's cloud. Samsung began phasing out free access to the SmartThings API in October 2026, and the integration now needs a paid SmartThings Personal Plan. The [SmartThings integration page](https://www.home-assistant.io/integrations/smartthings/) gives the price and the details.

LocalAppliances talks to supported Samsung appliances over your home network instead, so it needs no SmartThings account or subscription. This guide moves your appliances from the cloud integration to LocalAppliances and keeps your automations, scripts and dashboards working.

LocalAppliances covers appliances only: washers, dryers, dishwashers, refrigerators, ovens, ranges, cooktops, air conditioners and the other types in [What it supports](../README.md#what-it-supports). Samsung TVs have their own [Samsung Smart TV integration](https://www.home-assistant.io/integrations/samsungtv/). For Zigbee or Z-Wave devices you added through SmartThings, see the SmartThings integration page.

## Before you start

- **Keep each appliance in the SmartThings app.** Only the Home Assistant integration goes away. An appliance removed from SmartThings resets its network settings the next time it reaches Samsung's servers, and then drops off Wi-Fi. See [Known device behavior](../README.md#known-device-behavior).
- **Find each appliance's IP address**, for example in your router's list of connected devices. A fixed (reserved) address in your router saves a Reconfigure later.
- **Make a backup** in **Settings > System > Backups**.

## 1. Write down what uses each appliance

1. Go to **Settings > Devices & Services > Entities** and search for the appliance's name.
2. Open each entity that comes from SmartThings, open its settings, and note its **Entity ID**.
3. Open the device's page from **Settings > Devices & Services > SmartThings**. Its **Automations**, **Scripts** and **Scenes** cards list what refers to it. Dashboards are not listed there; check the ones you use.

Note which automations were built with **Device** triggers, conditions or actions in the visual editor. Those point at the SmartThings device itself, not at an entity ID, so step 5 can't carry them over. You will rebuild them.

## 2. Add the appliances to LocalAppliances

[Install LocalAppliances](../README.md#install) and [add each appliance](../README.md#add-an-appliance) by its IP address. Both integrations can run side by side while you compare: LocalAppliances connects to the appliance directly and the cloud integration goes through Samsung, so neither gets in the other's way.

Run a cycle or change a setting at the appliance, and check that the new entities follow it.

## 3. Match old entities to new ones

The two integrations read the same appliance but name and word things differently. These are the ones automations use most:

| SmartThings integration | LocalAppliances | Note |
|---|---|---|
| Machine state (sensor) | Machine state (sensor) | Washers, dryers, dishwashers: `stop`, `run`, `pause` become `idle`, `active`, `pause`. Ovens: `ready`, `running`, `paused` become `idle`, `active`, `pause`. |
| Job state (sensor), washer, dryer, dishwasher | Progress (sensor) | Values differ; see the list below. |
| Job state (sensor), oven | Cavity state (sensor) | `ready`, `preheat` and `cooking` keep their names; `finished` becomes `finish`. |
| Completion time (sensor) | Estimated finish (sensor) | Both are a date and time. LocalAppliances also has a sensor named **Completion time**, but it counts minutes left. Use Estimated finish. Estimated finish is shown only while a cycle runs. |
| Remote control (binary sensor) | Smart Control (binary sensor) | |
| Door (binary sensor) | Door (binary sensor) | Refrigerators with a sensor per compartment get one door sensor each, named after the compartment, such as "Freezer open". |
| Child lock (binary sensor) | Child lock (binary sensor) | |
| Water consumption (sensor) | Water consumption (sensor) | |
| Energy (sensor) | Energy (sensor) | |
| Power (sensor) | Power (sensor) | |
| Power cool, Power freeze (switch) | Rapid fridge, Rapid freezing (switch) | On some models these are read-only status sensors and can't be switched. |
| Climate entity (air conditioner) | Climate entity | |

SmartThings **Power energy** and **Energy difference** measure energy over each short reporting period. LocalAppliances has no equivalent, and its own **Power energy** sensor is a running total, so don't match them up.

**Progress values.** Where a washer, dryer or dishwasher automation waits for a Job state value, use the LocalAppliances value instead:

| SmartThings | LocalAppliances |
|---|---|
| `none` | `idle` |
| `delay_wash` | `delaywash` |
| `weight_sensing` | `weightsensing` |
| `pre_wash` | `prewash` |
| `pre_drain` | `predrain` |
| `air_wash` | `airwashing` |
| `wash`, `rinse`, `spin`, `drying`, `cooling`, `sanitizing` | same |
| `finish` (washer, dishwasher), `finished` (dryer) | `finish` |

Some SmartThings values, such as `ai_wash` and `wrinkle_prevent`, have no LocalAppliances equivalent.

There is also a **Running** binary sensor that is on while a cycle runs. Most "cycle finished" automations are simpler with it: trigger when Running turns off.

Which entities appear depends on what each appliance reports, so some rows may not apply to yours, and LocalAppliances may offer controls the cloud integration did not.

## 4. Remove the SmartThings integration

Deleting the integration removes **every** SmartThings device from Home Assistant at once, not just one appliance. Do it only after all your appliances work in LocalAppliances and nothing else you keep, such as a TV or a sensor, still depends on SmartThings. Until then, you can switch off one moved appliance's old device with **Disable** on its device page.

When you're ready, go to **Settings > Devices & Services > SmartThings**, open the menu next to the entry, and choose **Delete**. This deletes the cloud integration's devices and entities from Home Assistant. It does not remove anything from the SmartThings app.

The SmartThings integration page also says to delete the Home Assistant connection in the SmartThings app afterwards. That removes Home Assistant's access only. Leave the appliances themselves in the app.

## 5. Give the new entities the old IDs

For each entity ID you wrote down in step 1:

1. Open the matching LocalAppliances entity and its settings.
2. Change its **Entity ID** to the old one, and select **Update**.

The SmartThings entity is gone, so its ID is free. Automations, scripts and dashboards that use the ID now point at the LocalAppliances entity.

Then:

- **Rebuild automations that used Device triggers, conditions or actions** with the new LocalAppliances device. Renaming entity IDs doesn't reach them.
- **Check each automation that waits for a specific state value**, such as `run` or `finished`. Where the tables above show a different value, edit the automation to use the new one. Home Assistant can't do this for you, and an automation that waits for a value that never comes fails silently.

## 6. Check energy

Leave out energy sensors when you rename in step 5. The old and new sensors keep different running totals, and joining them under one ID can show as one huge day in the Energy dashboard. Instead, open **Settings > Dashboards > Energy**, remove the old SmartThings sensor, and add the LocalAppliances **Energy** sensor. If **Developer tools > Statistics** then lists a problem with the old sensor, follow the fix it offers.

## If something doesn't match

If a control or sensor you relied on has no LocalAppliances equivalent, open **Download diagnostics** on the device and attach the file to a [device-support issue](https://github.com/BrawnyBravo/LocalAppliances/issues/new?template=device-support.yml). Say which SmartThings entity you used. See [Reporting a capability gap](../README.md#reporting-a-capability-gap).
