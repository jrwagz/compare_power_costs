---
name: analyze-power-bill
description: Analyze a Rocky Mountain Power (RMP) monthly bill PDF for the user's account — decrypt if needed, then compare the actual time-of-use (TOU, Schedule 137) charges against the hypothetical Schedule 1 (non-TOU block) cost. Invoke when the user asks to analyze/review/compare a power bill, their latest RMP bill, or TOU vs non-TOU for a given billing period.
---

# Analyze Power Bill

Compares the actual billed TOU cost (Schedule 137) against what the same usage would have cost on the regular block schedule (Schedule 1), and produces a detailed markdown summary.

## Input

The user provides the bill PDF directly — either by attaching it to the message or by passing a filesystem path. If neither is present, ask them to supply one before proceeding.

## Decrypt

RMP bill PDFs are password-protected. Before running qpdf, **ask the user for the password** — do not assume or reuse a prior value. Ask once per skill invocation (a single bill). If the user volunteered the password in the invoking message, use that and skip the prompt.

Use `AskUserQuestion` (or a direct plain-text prompt if that tool is unavailable) with a question like: *"What's the password for this PDF?"*

Then strip the password with qpdf:

```
qpdf --password=<password> --decrypt "<input.pdf>" "<input>_nopw.pdf"
```

- If qpdf fails with an authentication error, ask the user to re-enter the password (typo is the likely cause). Retry up to twice before giving up.
- If qpdf reports the file is already unencrypted, continue with the original.
- Write the decrypted copy alongside the source with a `_nopw` suffix.
- **Never commit either PDF.** Both contain account details. If the project root is the working dir, add `*_nopw.pdf` and `Electronic_Bill_*.pdf` to `.gitignore` if not already ignored.
- Do not echo the password back in your response, write it to any file, or save it to memory.

Then `Read` the decrypted PDF to extract fields.

## Extract from the bill

From the "Detailed Account Activity" section for the Net Meter item (Schedule 137):

- **Service period** (from / to) and elapsed days
- **On-peak kWh** (net "onkwh" total — includes main minus subordinate meter)
- **Off-peak kWh** (net "offkwh" total)
- **Exported generation kWh** (from "Exported Cust Generation" line)
- **Base energy charges**: on-peak $ and off-peak $ (these are base rate × kWh, pre-fees/tax)
- **Rider rates** (the "cost per unit" column):
  - Renewable Energy Adjustment
  - Energy Balancing Account (EBA)
  - Wildfire Mitigation Bal Acct
  - Customer Efficiency Services
  - Elec Vehicle Infrastructure
- **Fixed items**: Basic Charge, Home Electric Lifeline Program, Paperless Bill Credit, Generation Export Credit
- **Tax rates**: Municipal Energy Sales/use Tax, Utah Sales Tax
- **Total New Charges** (the printed bill total)

Note the service-period end date — you need it to pick the right rate schedule.

## Compute Schedule 1 (non-TOU block) hypothetical

### 1. Choose the rate schedule

Use `compare_power_costs.py` as the source of truth. Read `RATE_SCHEDULES` and apply `get_rate_schedule(service_period_end_date)` logic: newest schedule whose `effective_date` ≤ end date.

If the bill's *on-peak/off-peak TOU rates* don't match the chosen schedule's `tou_*` fields to the penny, **stop and alert the user** — the rate table is out of date. Prepend a new `RateSchedule` entry before proceeding.

### 2. Season

- Summer (Jun–Sep, `SUMMER_MONTHS` in the code) → `block_summer_low`, `block_summer_high`
- Winter (Oct–May) → `block_winter_low`, `block_winter_high`

Determined by the service period's billing month (use end date's month).

### 3. Base energy on Schedule 1

Total net import = on-peak + off-peak kWh. Apply block pricing against **total net import**:

- First 400 kWh × low rate
- Remaining kWh × high rate
- Sum = new base energy charge

### 4. Scale the riders

The bill's riders apply to different bases. These empirical bases were validated against a real bill (reproduces the printed total within $0.05):

| Rider | Base |
|---|---|
| Renewable Energy Adjustment | base energy |
| Energy Balancing Account | base energy |
| Wildfire Mitigation | base energy + basic charge |
| Customer Efficiency Services | base energy + EBA + Renewable Adj |
| EV Infrastructure | base energy + EBA + Renewable Adj |

Apply each as `rate × base` using the *rates from the bill* (do not hardcode them — rates change).

### 5. Unchanged items

Keep these identical to the actual bill:
- Basic Charge
- Home Electric Lifeline Program
- Paperless Bill Credit
- Generation Export Credit (this reflects solar export, independent of tariff choice — but flag that Schedule 1 households aren't typically on Net Billing, so this credit may not actually apply)

### 6. Taxes

Pre-tax subtotal = sum of all above. Then:
- Municipal Energy Tax: subtotal × municipal rate (typically 6%)
- Utah Sales Tax: subtotal × state rate (typically 4.6%)

Schedule 1 total = subtotal + both taxes.

## Verify before reporting

Re-run steps 4–6 using the bill's *actual* base energy charges (on-peak $ + off-peak $). The reconstructed total must match the printed "Total New Charges" to within $0.05. If not:

- Do not report numbers.
- Show the user the discrepancy line-by-line and stop.

This catches rate-table drift, extraction errors, and changes to how RMP computes riders.

## Report format

Produce a markdown summary with these sections:

1. **Actual TOU bill** — service period, days, on-peak / off-peak / exported kWh, printed total.
2. **Schedule 1 hypothetical** — line-item table (block breakdown, each rider, taxes, total).
3. **Bottom line** — side-by-side totals, $ delta, % delta, which schedule is cheaper.
4. **Why** — on-peak share of import (%), one-sentence explanation of what drives the delta.

Keep it tight. One table per section, no prose filler.

## Cleanup

Leave the `_nopw.pdf` in place (user may want it for reference) unless the user asks to delete it. Do not delete the source PDF.

## Caveats to mention in the report

- The Schedule 1 figure assumes all riders scale as on the sample bill. Real Schedule 1 bills may apply different rider bases; treat the number as an estimate within ~1–2%.
- Schedule 137's Net Billing Program credits exported kWh. Moving to Schedule 1 would likely change how exports are credited, so the apparent delta understates the true gap when the customer has solar.
