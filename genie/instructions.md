# Genie space — DSV Parcel Express Data Workbench

**Purpose:** let DSV data analysts and business users ask questions about booking
**volume** and booking **quality** in natural language, over the governed Gold marts.

## Tables to include
- `dsv.silver.bookings_clean` — granular booking-level fact (for drill-down / ad-hoc)
- `dsv.gold.volume_daily_by_mode`
- `dsv.gold.lane_concentration`
- `dsv.gold.booking_velocity`
- `dsv.gold.quality_by_channel`
- `dsv.gold.completeness_breakdown`
- `dsv.gold.quality_monthly_trend`
- `dsv.gold.defect_classification_flat` (GenAI defect categories)

## General instructions (paste into the Genie space)
- This is a **freight-forwarding / Parcel Express** dataset. A "booking" is a shipment order.
- **First-Time-Right (FTR)** = `first_time_right = true`: booking processed with no manual correction. Report FTR as a percentage (`avg(first_time_right::int)`).
- **Automation / electronic-integration share** = share of bookings via `channel IN ('API','EDI')` (`is_electronic = true`). EMAIL, PORTAL and FAX_OCR are non-automated.
- **Amendment rate** = share of bookings with `amendment_count > 0`.
- **No-show** = `no_show = true` (phantom booking, cargo never arrived).
- **Lane** = `origin_hub`-`destination_hub`. "High-value / concentrated lanes" = lanes with the most bookings or weight.
- **Capacity utilization** = `booked_capacity / available_capacity`; low utilization means wasted space, >1 means overbooking pressure.
- **Booking velocity / lead time** = `lead_time_days` (days between booking and departure). "Booking early" = large lead time.
- Modes are AIR, OCEAN, ROAD. Ocean uses TEU, road uses LDM (loading meters), air uses chargeable_kg.
- When asked "by month" use `booking_month`; "by week" use `booking_week`; "by day" use `booking_date`.
- Always prefer the Gold marts for aggregates; use `bookings_clean` only for granular/ad-hoc drill-down.

## Sample question titles (add as saved questions)
- What is our overall First-Time-Right rate?
- Show FTR rate by booking channel.
- What share of bookings arrive via automated channels (EDI/API) each month?
- Which trade lanes have the highest volume?
- What is the average booking lead time by mode?
- Which completeness defect is most common on FAX_OCR bookings?
- What is the no-show rate trend by month?
- What are the top GenAI defect categories and their remediation?
