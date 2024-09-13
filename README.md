# Rocky Mountain Power Electric Vehicle Pricing Plan Comparison Tool

This tool is intended as a way to compare Rocky Mountain Power pricing, most likely for those
considering participating in the
[program](https://www.rockymountainpower.net/savings-energy-choices/electric-vehicles/utah-ev-time-of-use-rate.html).

## How to Use

To run the analysis, simply do the following:

```text
./compare_rmp_power_costs.py ./2024-09
```

Which should produce an output that looks like this:

```bash
$ ./compare_power_costs.py ./2024-09
{
    "2024-09": {
        "kWh": 1017.812,
        "block_cost": 108.52534451999998,
        "ev_cost": 84.54802316799999,
        "difference": 23.97732135199999
    },
    "SUMMARY": {
        "kWh": 1017.812,
        "block_cost": 108.52534451999998,
        "ev_cost": 84.54802316799999,
        "difference": 23.97732135199999
    }
}
```

This example output is saying that for the example data, the base price (before taxes, surcharges,
and fees) of electricity would be $108.53 on the "standard" block based pricing schedule, and would
be $84.55 on the EV time of day based pricing schedule.  Furthermore it shows that the difference is
$23.97 in favor of the EV time of day pricing schedule.

The repo provides some sample data for clarity purposes, however in order to get an answer as to
whether or not it's worth switching for yourself, you'll need to get your own data and provide it to
the script to analyze.

## How to get my data to compare?

- Login to the [Rocky Mountain Power
  website](https://csapps.rockymountainpower.net/secure/my-account/energy-usage) with your
  credentials.
- Visit the [Energy Usage](https://csapps.rockymountainpower.net/secure/my-account/energy-usage) page.
- Change the time period to "One Day"
- Change the date selection to the day whose data you want to collect.
- Click "Download Usage History" which should download a single CSV file.
- Name that file `YYYY-MM-DD.csv`, so if the data is for the 11th of August, 2024, it should be
  named `2024-09-11.csv`.
- Place all of these CSV files into a single folder
- When you call the python script, pass in a reference to the folder where the CSV files are stored,
  so that the script knows where to find them.

### FAQs

> Why do I need to name the file `YYYY-MM-DD.csv`?

Rocky mountain power does not include any information in the default CSV file to designate which day
the usage is for.  Therefore we need to put the date into the file name so that we can accurately
determine the time of day price.

> Is there a way to download many days at once?

Perhaps! I'm not sure.  I've done some digging into the Rocky Mountain Power websites API for this
data, but didn't get very far.  This is why I just defaulted to manually downloading the files day
by day one at a time, since I felt that was faster than developing a way to directly poll the Rocky
Mountain Power's API.

> What is "block pricing"?

This is the Rocky Mountain Power pricing schedule where the first 400kWh in a month are one price,
and any additional are another price.  It's fully defined
[here](https://www.rockymountainpower.net/content/dam/pcorp/documents/en/rockymountainpower/rates-regulation/utah/rates/001_Residential_Service.pdf)

> What is "EV pricing"?

This is the Rocky Mountain Power pricing schedule where the price per kWh changes based on the hour
of the day, and whether or not it's a holiday.  It's fully defined
[here](https://www.rockymountainpower.net/content/dam/pcorp/documents/en/rockymountainpower/rates-regulation/utah/rates/002E_Residential_Service_Electric_Vehicle_Time_of_Use_Pilot.pdf)