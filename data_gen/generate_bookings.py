"""
DSV Parcel Express — synthetic booking generator.

Generates a single, unified raw booking dataset that supports BOTH:
  * Booking Volume Analysis  (capacity, seasonality, velocity/lead time, lane concentration)
  * Booking Quality Analysis (First-Time-Right, completeness, amendments, channel mix, no-shows)

The data is SYNTHETIC. No real customer data is used. Realistic behaviour is baked in:
  * Q4 seasonal peak + weekly cycle (fewer weekend bookings)
  * Channel-correlated defect rates (manual email / fax-OCR are worse than EDI/API)
  * Pareto lane concentration (a few lanes carry most volume)
  * Booking lead time distribution (most bookings arrive days before departure)
  * Free-text defect_reason on failed bookings (feeds the GenAI defect classifier)

Output: newline-delimited JSON shards under data_gen/out/ (raw landing files for Lakeflow),
plus a small CSV sample and a schema doc committed to the repo.

Run:
  python data_gen/generate_bookings.py --rows 400000 --shards 8 --out data_gen/out
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

RNG_SEED = 20260922

# ---------------------------------------------------------------------------
# Reference dimensions
# ---------------------------------------------------------------------------
MODES = ["AIR", "OCEAN", "ROAD"]
MODE_WEIGHTS = [0.30, 0.20, 0.50]  # Parcel Express skews to road for regional B2B

# Channels and their relative share + baseline first-time-right probability.
# Automated channels (EDI/API) are cleaner; manual/OCR channels are error prone.
CHANNELS = {
    "API":        {"share": 0.34, "ftr_base": 0.965},
    "EDI":        {"share": 0.28, "ftr_base": 0.955},
    "PORTAL":     {"share": 0.14, "ftr_base": 0.910},
    "EMAIL":      {"share": 0.16, "ftr_base": 0.760},
    "FAX_OCR":    {"share": 0.08, "ftr_base": 0.640},
}

CUSTOMER_TYPES = {
    "SPARE_PARTS": 0.40,
    "SAMPLES":     0.18,
    "PRODUCTION":  0.27,
    "HEALTHCARE":  0.15,
}

# Origin/destination hubs (IATA-ish codes) with weights to create lane concentration.
HUBS = {
    "CPH": 0.10, "AMS": 0.13, "FRA": 0.14, "LHR": 0.09, "CDG": 0.08,
    "MAD": 0.06, "MIL": 0.06, "HAM": 0.07, "ARN": 0.05, "OSL": 0.04,
    "JFK": 0.06, "ORD": 0.03, "SIN": 0.04, "HKG": 0.03, "DXB": 0.02,
}
HUB_COUNTRY = {
    "CPH": "DK", "AMS": "NL", "FRA": "DE", "LHR": "GB", "CDG": "FR",
    "MAD": "ES", "MIL": "IT", "HAM": "DE", "ARN": "SE", "OSL": "NO",
    "JFK": "US", "ORD": "US", "SIN": "SG", "HKG": "HK", "DXB": "AE",
}

SERVICE_CODES = ["EXP-09", "EXP-12", "STD-EOD", "ECON-48", "HEALTH-CTRL", "SAME-DAY"]

# Free-text defect reasons keyed by the completeness flag that triggered them.
DEFECT_TEXTS = {
    "missing_address": [
        "Receiver address incomplete - no postal code provided by shipper.",
        "Delivery street line blank, only city given.",
        "Consignee contact name and door number missing.",
    ],
    "missing_customs_doc": [
        "Commercial invoice not attached for cross-border shipment.",
        "HS code missing on customs declaration.",
        "No EORI number supplied for dutiable goods.",
    ],
    "wrong_weight": [
        "Declared weight 2kg but scanned gross weight 18kg - reweigh required.",
        "Volumetric weight mismatch vs booked chargeable weight.",
        "Dimensions imply pallet, booked as parcel.",
    ],
    "missing_service_code": [
        "Service level code not mapped - defaulted, needs manual confirmation.",
        "Healthcare cold-chain requested but no temperature service code.",
        "Ambiguous service selection between express and economy.",
    ],
    "other": [
        "Duplicate booking suspected against same reference.",
        "Pickup window conflicts with carrier cut-off time.",
        "Special handling flag set without hazmat paperwork.",
    ],
}


def _weighted_choice(rng, keys, weights, size):
    weights = np.asarray(weights, dtype=float)
    weights = weights / weights.sum()
    return rng.choice(keys, size=size, p=weights)


def _seasonal_weight(day_of_year: np.ndarray) -> np.ndarray:
    """Higher booking density toward Q4 (peak season) with a summer dip."""
    # Base sinusoid peaking around day ~330 (late Nov / Black Friday-Christmas run-up)
    phase = 2 * np.pi * (day_of_year - 330) / 365.0
    return 1.0 + 0.45 * np.cos(phase)


def generate(rows: int, seed: int = RNG_SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    start = datetime(2025, 1, 1)
    horizon_days = 540  # ~18 months

    # --- booking timestamps with seasonal + weekly weighting -----------------
    # Sample candidate days, weight by season, down-weight weekends.
    days = np.arange(horizon_days)
    doy = ((start + pd.to_timedelta(days, unit="D")).dayofyear).to_numpy()
    day_weight = _seasonal_weight(doy)
    weekday = ((start.weekday() + days) % 7)
    day_weight = day_weight * np.where(weekday >= 5, 0.35, 1.0)  # fewer weekend bookings
    day_weight = day_weight / day_weight.sum()

    chosen_days = rng.choice(days, size=rows, p=day_weight)
    secs = rng.integers(6 * 3600, 20 * 3600, size=rows)  # business hours bias
    booking_ts = pd.to_datetime(start) + pd.to_timedelta(chosen_days, unit="D") + pd.to_timedelta(secs, unit="s")

    # --- lead time (days from booking to departure) --------------------------
    # Right-skewed: most bookings are a few days ahead; some same-day, some far out.
    lead_days = np.clip(rng.gamma(shape=2.0, scale=2.6, size=rows), 0, 45)
    departure_ts = booking_ts + pd.to_timedelta((lead_days * 86400).astype(int), unit="s")

    # --- mode, channel, customer, lane ---------------------------------------
    mode = _weighted_choice(rng, MODES, MODE_WEIGHTS, rows)
    channel = _weighted_choice(rng, list(CHANNELS), [c["share"] for c in CHANNELS.values()], rows)
    customer_type = _weighted_choice(rng, list(CUSTOMER_TYPES), list(CUSTOMER_TYPES.values()), rows)

    hub_keys = list(HUBS)
    origin = _weighted_choice(rng, hub_keys, list(HUBS.values()), rows)
    destination = _weighted_choice(rng, hub_keys, list(HUBS.values()), rows)
    # avoid origin == destination
    same = origin == destination
    destination = np.where(same, rng.choice(hub_keys, size=rows), destination)

    # Customer id pool with a Pareto-ish concentration (a few big shippers).
    n_customers = 220
    cust_pop = np.arange(n_customers)
    cust_w = 1.0 / (cust_pop + 3) ** 0.85
    cust_w = cust_w / cust_w.sum()
    customer_id = _weighted_choice(rng, cust_pop, cust_w, rows)
    customer_id = np.array([f"CUST-{c:04d}" for c in customer_id])

    # --- volumetrics ---------------------------------------------------------
    weight_kg = np.round(np.clip(rng.lognormal(mean=2.4, sigma=1.0, size=rows), 0.2, 2500), 2)
    density = rng.uniform(80, 320, size=rows)  # kg/m3
    volume_m3 = np.round(weight_kg / density, 4)
    # chargeable units per mode
    teu = np.where(mode == "OCEAN", np.round(volume_m3 / 33.0, 4), 0.0)          # ~33 m3/TEU
    ldm = np.where(mode == "ROAD", np.round(volume_m3 / 1.76, 3), 0.0)           # loading meters
    chargeable_kg = np.where(mode == "AIR", np.maximum(weight_kg, volume_m3 * 167), 0.0)

    # capacity context for utilization analysis
    available_capacity = np.where(
        mode == "OCEAN", rng.uniform(20, 60, rows),      # TEU on the sailing allotment
        np.where(mode == "ROAD", rng.uniform(8, 13.6, rows),  # LDM per trailer
                 rng.uniform(5000, 20000, rows)))          # kg air allotment
    booked_capacity = np.where(
        mode == "OCEAN", teu,
        np.where(mode == "ROAD", ldm, chargeable_kg))

    service_code = rng.choice(SERVICE_CODES, size=rows)
    # healthcare tends to use controlled service
    service_code = np.where((customer_type == "HEALTHCARE") & (rng.random(rows) < 0.6),
                            "HEALTH-CTRL", service_code)

    # --- quality signals -----------------------------------------------------
    ftr_base = np.array([CHANNELS[c]["ftr_base"] for c in channel])
    # extra difficulty for healthcare/customs-heavy and far international lanes
    intl = np.array([HUB_COUNTRY[o] for o in origin]) != np.array([HUB_COUNTRY[d] for d in destination])
    difficulty = (
        0.06 * intl
        + 0.04 * (customer_type == "HEALTHCARE")
        + 0.03 * (mode == "AIR")
    )
    ftr_prob = np.clip(ftr_base - difficulty, 0.30, 0.995)
    first_time_right = rng.random(rows) < ftr_prob

    # completeness flags only meaningful when NOT first-time-right (mostly)
    fail = ~first_time_right
    def flag(p_fail):
        return fail & (rng.random(rows) < p_fail)
    missing_address = flag(0.35)
    missing_customs_doc = intl & flag(0.40)
    wrong_weight = flag(0.30)
    missing_service_code = flag(0.25)

    # amendments: correlated with failures and manual channels
    amend_lambda = np.where(first_time_right, 0.05, 1.4) + np.isin(channel, ["EMAIL", "FAX_OCR"]) * 0.3
    amendment_count = rng.poisson(amend_lambda)

    # cancellations / no-shows: rare, higher for low quality + long lead time
    cancel_prob = np.clip(0.015 + 0.05 * fail + 0.02 * (lead_days > 20), 0, 0.4)
    cancelled = rng.random(rows) < cancel_prob
    no_show = (~cancelled) & (rng.random(rows) < np.clip(0.008 + 0.03 * fail, 0, 0.2))

    # defect_reason free text (only on failures; pick the dominant flag)
    defect_reason = np.array([""] * rows, dtype=object)
    for i in np.where(fail)[0]:
        if missing_customs_doc[i]:
            key = "missing_customs_doc"
        elif missing_address[i]:
            key = "missing_address"
        elif wrong_weight[i]:
            key = "wrong_weight"
        elif missing_service_code[i]:
            key = "missing_service_code"
        else:
            key = "other"
        defect_reason[i] = rng.choice(DEFECT_TEXTS[key])

    booking_id = np.array([f"BK-{2025_000000 + i:012d}" for i in range(rows)])

    df = pd.DataFrame({
        "booking_id": booking_id,
        "booking_ts": booking_ts,
        "departure_ts": departure_ts,
        "lead_time_days": np.round(lead_days, 2),
        "mode": mode,
        "channel": channel,
        "customer_id": customer_id,
        "customer_type": customer_type,
        "origin_hub": origin,
        "origin_country": [HUB_COUNTRY[o] for o in origin],
        "destination_hub": destination,
        "destination_country": [HUB_COUNTRY[d] for d in destination],
        "is_international": intl,
        "service_code": service_code,
        "weight_kg": weight_kg,
        "volume_m3": volume_m3,
        "teu": teu,
        "ldm": ldm,
        "chargeable_kg": np.round(chargeable_kg, 2),
        "booked_capacity": np.round(booked_capacity, 4),
        "available_capacity": np.round(available_capacity, 4),
        "first_time_right": first_time_right,
        "missing_address": missing_address,
        "missing_customs_doc": missing_customs_doc,
        "wrong_weight": wrong_weight,
        "missing_service_code": missing_service_code,
        "amendment_count": amendment_count.astype(int),
        "cancelled": cancelled,
        "no_show": no_show,
        "defect_reason": defect_reason,
    })
    return df.sort_values("booking_ts").reset_index(drop=True)


def write_shards(df: pd.DataFrame, out_dir: str, shards: int) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    parts = np.array_split(df, shards)
    for i, part in enumerate(parts):
        path = os.path.join(out_dir, f"bookings_part_{i:02d}.jsonl")
        # newline-delimited JSON; timestamps as ISO strings for raw landing
        rec = part.copy()
        rec["booking_ts"] = rec["booking_ts"].astype(str)
        rec["departure_ts"] = rec["departure_ts"].astype(str)
        rec.to_json(path, orient="records", lines=True)
        paths.append(path)
    return paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=400000)
    ap.add_argument("--shards", type=int, default=8)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "out"))
    ap.add_argument("--seed", type=int, default=RNG_SEED)
    args = ap.parse_args()

    print(f"Generating {args.rows:,} synthetic Parcel Express bookings (seed={args.seed}) ...")
    df = generate(args.rows, args.seed)
    paths = write_shards(df, args.out, args.shards)

    # committed artifacts: a small CSV sample + summary printed to stdout (evidence)
    sample_path = os.path.join(os.path.dirname(__file__), "sample_bookings.csv")
    df.head(200).to_csv(sample_path, index=False)

    print(f"Wrote {len(paths)} shards to {args.out}")
    print(f"Sample (200 rows) -> {sample_path}")
    print("\n=== SUMMARY (synthetic) ===")
    print(f"rows: {len(df):,}")
    print(f"date range: {df.booking_ts.min()} .. {df.booking_ts.max()}")
    print(f"overall first_time_right: {df.first_time_right.mean():.3f}")
    print("\nFTR by channel:")
    print(df.groupby('channel').first_time_right.mean().round(3).to_string())
    print("\nChannel mix (automation share):")
    print((df.channel.value_counts(normalize=True).round(3)).to_string())
    print("\nBookings by mode:")
    print(df['mode'].value_counts().to_string())
    print(f"\namendment rate (>0): {(df.amendment_count>0).mean():.3f}")
    print(f"cancel rate: {df.cancelled.mean():.3f}  no-show rate: {df.no_show.mean():.3f}")
    print(f"defect_reason populated: {(df.defect_reason.str.len()>0).mean():.3f}")


if __name__ == "__main__":
    main()
