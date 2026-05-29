"""Registry of ACN-Sim stock scheduling algorithms.

Seven baselines ship out of the box — no custom code. All are V1G; all
operate on the standard ACN-Sim Algorithm interface.

Differentiation note: with v2b's default 1:1 car→station mapping and
ev_count ≤ n_chargers, sort-order variants (EDF/LLF/FCFS/LCFS/LRPT)
often converge to the same schedule because there's no per-tick
contention. They differ on **oversubscribed** scenarios (fleet ≫
chargers — see `S_audit_baseline` or post-W4 scaled scenarios).
RoundRobin and UncontrolledCharging always differ from the sorted set.
"""
from __future__ import annotations

from acnportal.algorithms import (
    RoundRobin,
    SortedSchedulingAlgo,
    UncontrolledCharging,
    earliest_deadline_first,
    first_come_first_served,
    largest_remaining_processing_time,
    last_come_first_served,
    least_laxity_first,
)


def _edf():
    return SortedSchedulingAlgo(earliest_deadline_first)


def _llf():
    return SortedSchedulingAlgo(least_laxity_first)


def _fcfs():
    return SortedSchedulingAlgo(first_come_first_served)


def _lcfs():
    return SortedSchedulingAlgo(last_come_first_served)


def _lrpt():
    return SortedSchedulingAlgo(largest_remaining_processing_time)


def _round_robin():
    # RoundRobin needs a sort_fn for tie-breaking; FCFS is the stable choice.
    return RoundRobin(first_come_first_served)


def _uncontrolled():
    return UncontrolledCharging()


ALGORITHMS = {
    "edf":          _edf,              # Earliest-Deadline-First
    "llf":          _llf,              # Least-Laxity-First
    "fcfs":         _fcfs,             # First-Come-First-Served
    "lcfs":         _lcfs,             # Last-Come-First-Served
    "lrpt":         _lrpt,             # Largest-Remaining-Processing-Time
    "round_robin":  _round_robin,
    "uncontrolled": _uncontrolled,     # no scheduler — upper-bound peak
}


def available_algorithms() -> list[str]:
    return sorted(ALGORITHMS.keys())
