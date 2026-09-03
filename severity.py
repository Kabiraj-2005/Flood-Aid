"""
Severity scoring.

This is deliberately a plain formula, not a model. Two reasons:
  1. There is no labelled data on rescue outcomes, so a trained ranker would
     be guessing with extra steps.
  2. A dispatcher can see every term and argue with it. A model they cannot
     see, they will not trust.

The waiting-time term is the important one. Without it, a remote incident
never wins against a stream of closer ones and waits forever.
"""

import math
import time

WEIGHTS = {
    "injured": 3.0,
    "vulnerable": 2.0,      # children or elderly present
    "people": 1.5,          # log-scaled, so 100 people is not 10x worse than 10
    "rising": 2.0,
    "cut_off": 2.0,         # road not passable
    "waiting": 1.0,         # per hour
}

WATER_DEPTH = {"ankle": 0.5, "knee": 1.0, "waist": 2.0, "above": 3.0}


MAX_WAIT_HOURS = 24.0   # a report older than this is stale, not infinitely urgent


def hours_waiting(report: dict, now_ms: int) -> float:
    """
    How long this has been waiting, in hours.

    reported_at comes from the PHONE clock, which is not trustworthy — a device
    stuck in 2019 would otherwise score as having waited fifty thousand hours
    and jump the queue forever. So we take whichever is later, the phone time
    or the time the server first saw it, and cap the result.
    """
    reported = report.get("reported_at") or now_ms
    seen = report.get("synced_at") or now_ms
    start = max(reported, min(seen, now_ms))          # never before the server saw it
    hrs = (now_ms - start) / 3_600_000
    return max(0.0, min(hrs, MAX_WAIT_HOURS))


def compute_severity(report: dict, now_ms: int | None = None) -> float:
    """Return a severity score. Higher is more urgent."""
    now_ms = now_ms or int(time.time() * 1000)
    s = 0.0

    if report.get("injured"):
        s += WEIGHTS["injured"]

    if report.get("children_elderly"):
        s += WEIGHTS["vulnerable"]

    people = report.get("people_count") or 0
    if people > 0:
        s += WEIGHTS["people"] * math.log1p(people)

    if report.get("rising"):
        s += WEIGHTS["rising"]

    if report.get("road_passable") == "no":
        s += WEIGHTS["cut_off"]

    s += WATER_DEPTH.get(report.get("water_level") or "", 0.0)

    s += WEIGHTS["waiting"] * hours_waiting(report, now_ms)

    return round(s, 2)


def explain(report: dict, now_ms: int | None = None) -> list[str]:
    """
    Human-readable breakdown, shown next to the score in the control room.
    If you cannot explain a priority, a dispatcher should not act on it.
    """
    now_ms = now_ms or int(time.time() * 1000)
    parts = []

    if report.get("injured"):
        parts.append(f"injured present +{WEIGHTS['injured']}")
    if report.get("children_elderly"):
        parts.append(f"children or elderly +{WEIGHTS['vulnerable']}")

    people = report.get("people_count") or 0
    if people > 0:
        parts.append(
            f"{people} people +{round(WEIGHTS['people'] * math.log1p(people), 2)}"
        )
    if report.get("rising"):
        parts.append(f"water rising +{WEIGHTS['rising']}")
    if report.get("road_passable") == "no":
        parts.append(f"road cut off +{WEIGHTS['cut_off']}")

    depth = WATER_DEPTH.get(report.get("water_level") or "", 0.0)
    if depth:
        parts.append(f"{report['water_level']} deep +{depth}")

    hrs = hours_waiting(report, now_ms)
    if hrs > 0.05:
        parts.append(f"waiting {hrs:.1f} h +{round(WEIGHTS['waiting'] * hrs, 2)}")

    return parts
