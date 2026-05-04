"""
candidates.py — routing engine.

Pure function: given (origin, destination, max_stops, include_train), returns
a list of Itinerary candidates. No network, no I/O, no hidden state. Same
input → same output.

Layering: imports from nodes.py and connections.py. Imported by pricer.py.
Never import pricer or currency from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from nodes import NODES, Node
from connections import TrainConnection, get_train_connections_from


# ---------- Mode constants ----------

FLIGHT = "FLIGHT"
TRAIN = "TRAIN"


# ---------- Data classes ----------

@dataclass
class Leg:
    mode: str                       # FLIGHT or TRAIN
    origin: str                     # node code
    destination: str                # node code
    duration_min: Optional[int] = None   # populated for trains; flights filled in by pricer
    cost_cny: Optional[int] = None       # same — train fare in CNY (source-of-truth)
    notes: str = ""


@dataclass
class Itinerary:
    legs: list[Leg]

    @property
    def origin(self) -> str:
        return self.legs[0].origin

    @property
    def destination(self) -> str:
        return self.legs[-1].destination

    @property
    def num_stops(self) -> int:
        """Number of intermediate stops counting ALL legs.

        Note: a train+fly itinerary is counted as 1 stop per leg, so
        `train → fly → fly` returns num_stops=2 even though there's only
        one flight transit. Callers filtering by num_stops should account
        for this if they care about flight-only stop counts.
        """
        return max(0, len(self.legs) - 1)

    @property
    def hub_codes(self) -> list[str]:
        """Intermediate transit codes between origin and destination."""
        return [leg.destination for leg in self.legs[:-1]]

    @property
    def has_train_leg(self) -> bool:
        return any(leg.mode == TRAIN for leg in self.legs)

    def describe(self) -> str:
        """Render as 'CKG → HKG → VIE' with rail transfers flagged."""
        parts: list[str] = [self.legs[0].origin]
        for i, leg in enumerate(self.legs):
            arrow = " ⇒ " if leg.mode == TRAIN else " → "
            # If the next leg's origin differs from this leg's destination,
            # render a transfer hint (e.g. HKG-WK → fly out of HKG).
            next_leg = self.legs[i + 1] if i + 1 < len(self.legs) else None
            if next_leg is not None and next_leg.origin != leg.destination:
                parts.append(arrow + f"{leg.destination} (transfer to {next_leg.origin})")
            else:
                parts.append(arrow + leg.destination)
        return "".join(parts)


# Rail nodes that aren't co-located with an airport must transfer to a nearby
# airport before the next flight leg. Maps rail-arrival code → flight-departure code.
RAIL_TO_AIRPORT: dict[str, str] = {
    "HKG-WK": "HKG",   # West Kowloon HSR → HKG airport (~30–40min)
    # CKG-N → CKG is implicit (CKG-N is only ever an *origin* for trains)
}


# ---------- Geographic transit rules ----------
#
# TRANSIT_REGIONS[frozenset({region_a, region_b})] returns the set of regions
# that are valid transit zones for that origin/destination pair. Without this
# filter, every search would return nonsense like CKG → LHR via BKK.
#
# For same-region routes, frozenset({"CHINA"}) lookup uses the single-element key.
TRANSIT_REGIONS: dict[frozenset[str], set[str]] = {
    # Within-region (domestic + intra-area)
    frozenset({"CHINA"}):           {"CHINA"},
    frozenset({"GREATER_CHINA"}):   {"CHINA", "GREATER_CHINA"},
    frozenset({"SOUTHEAST_ASIA"}):  {"SOUTHEAST_ASIA"},
    frozenset({"EAST_ASIA"}):       {"EAST_ASIA"},
    frozenset({"EUROPE"}):          {"EUROPE"},
    frozenset({"MIDDLE_EAST"}):     {"MIDDLE_EAST"},
    frozenset({"NORTH_AMERICA"}):   {"NORTH_AMERICA"},

    # Cross-region pairs (lookup is order-independent via frozenset)
    frozenset({"CHINA", "GREATER_CHINA"}):    {"CHINA", "GREATER_CHINA"},
    frozenset({"CHINA", "EAST_ASIA"}):        {"CHINA", "GREATER_CHINA", "EAST_ASIA"},
    frozenset({"CHINA", "SOUTHEAST_ASIA"}):   {"CHINA", "GREATER_CHINA", "SOUTHEAST_ASIA"},
    frozenset({"CHINA", "MIDDLE_EAST"}):      {"CHINA", "GREATER_CHINA", "MIDDLE_EAST"},
    frozenset({"CHINA", "EUROPE"}):           {"CHINA", "GREATER_CHINA", "EAST_ASIA", "MIDDLE_EAST", "EUROPE"},
    frozenset({"CHINA", "NORTH_AMERICA"}):    {"CHINA", "GREATER_CHINA", "EAST_ASIA", "NORTH_AMERICA"},

    frozenset({"GREATER_CHINA", "EAST_ASIA"}):       {"CHINA", "GREATER_CHINA", "EAST_ASIA"},
    frozenset({"GREATER_CHINA", "SOUTHEAST_ASIA"}):  {"GREATER_CHINA", "SOUTHEAST_ASIA"},
    frozenset({"GREATER_CHINA", "MIDDLE_EAST"}):     {"GREATER_CHINA", "MIDDLE_EAST"},
    frozenset({"GREATER_CHINA", "EUROPE"}):          {"GREATER_CHINA", "EAST_ASIA", "MIDDLE_EAST", "EUROPE"},
    frozenset({"GREATER_CHINA", "NORTH_AMERICA"}):   {"GREATER_CHINA", "EAST_ASIA", "NORTH_AMERICA"},

    frozenset({"SOUTHEAST_ASIA", "EAST_ASIA"}):    {"SOUTHEAST_ASIA", "GREATER_CHINA", "EAST_ASIA"},
    frozenset({"SOUTHEAST_ASIA", "MIDDLE_EAST"}):  {"SOUTHEAST_ASIA", "MIDDLE_EAST"},
    frozenset({"SOUTHEAST_ASIA", "EUROPE"}):       {"SOUTHEAST_ASIA", "MIDDLE_EAST", "EUROPE"},
    frozenset({"SOUTHEAST_ASIA", "NORTH_AMERICA"}): {"SOUTHEAST_ASIA", "EAST_ASIA", "NORTH_AMERICA"},

    frozenset({"EAST_ASIA", "MIDDLE_EAST"}):       {"EAST_ASIA", "MIDDLE_EAST"},
    frozenset({"EAST_ASIA", "EUROPE"}):            {"EAST_ASIA", "MIDDLE_EAST", "EUROPE"},
    frozenset({"EAST_ASIA", "NORTH_AMERICA"}):     {"EAST_ASIA", "NORTH_AMERICA"},

    frozenset({"MIDDLE_EAST", "EUROPE"}):          {"MIDDLE_EAST", "EUROPE"},
    frozenset({"MIDDLE_EAST", "NORTH_AMERICA"}):   {"MIDDLE_EAST", "EUROPE", "NORTH_AMERICA"},

    frozenset({"EUROPE", "NORTH_AMERICA"}):        {"EUROPE", "NORTH_AMERICA"},
}

# Destinations classified as longhaul. When the destination is in this set,
# train+fly itineraries are also generated with a 1-stop flight extension.
LONGHAUL_REGIONS: set[str] = {"EUROPE", "NORTH_AMERICA"}


def _valid_transit_regions(origin_region: str, destination_region: str) -> set[str]:
    """Look up the set of valid transit regions for an origin/destination pair."""
    key = frozenset({origin_region, destination_region})
    return TRANSIT_REGIONS.get(key, {origin_region, destination_region})


def _airport_hubs_in_regions(regions: set[str], exclude: set[str]) -> list[Node]:
    """All airport-type hub nodes in any of the given regions, excluding `exclude` codes."""
    return [
        n for n in NODES.values()
        if n.region in regions
        and n.is_hub
        and n.node_type == "airport"
        and n.code not in exclude
    ]


# ---------- Candidate generation ----------

def generate_candidates(
    origin_code: str,
    destination_code: str,
    max_stops: int = 1,
    include_train: bool = True,
) -> list[Itinerary]:
    """Generate every plausible Itinerary for (origin, destination).

    Pure function: same inputs → same outputs. No network, no I/O.

    Stages:
      1. Always include the direct flight as candidate #1.
      2. If max_stops >= 1, generate 1-stop options through valid transit hubs.
      3. If max_stops >= 2, generate 2-stop options (different-region pairs).
      4. If origin == "CKG" and include_train, generate train+fly options
         (with a longhaul train+1-stop extension when max_stops >= 1 and
         the destination is in EUROPE / NORTH_AMERICA).
    """
    # Validate endpoints exist in NODES (raises KeyError on miss).
    origin: Node = NODES[origin_code]
    destination: Node = NODES[destination_code]

    candidates: list[Itinerary] = []

    # Stage 1: direct flight (always)
    candidates.append(Itinerary(legs=[
        Leg(mode=FLIGHT, origin=origin_code, destination=destination_code),
    ]))

    # Stage 2: 1-stop via valid transit hubs
    if max_stops >= 1:
        regions = _valid_transit_regions(origin.region, destination.region)
        hubs = _airport_hubs_in_regions(regions, exclude={origin_code, destination_code})
        for hub in hubs:
            candidates.append(Itinerary(legs=[
                Leg(mode=FLIGHT, origin=origin_code, destination=hub.code),
                Leg(mode=FLIGHT, origin=hub.code, destination=destination_code),
            ]))

    # Stage 2b: 2-stop via different-region hub pairs (avoids backtracking)
    if max_stops >= 2:
        regions = _valid_transit_regions(origin.region, destination.region)
        hubs = _airport_hubs_in_regions(regions, exclude={origin_code, destination_code})
        for hub_a in hubs:
            for hub_b in hubs:
                if hub_a.code == hub_b.code:
                    continue
                if hub_a.region == hub_b.region:
                    continue   # no same-region backtracking
                candidates.append(Itinerary(legs=[
                    Leg(mode=FLIGHT, origin=origin_code, destination=hub_a.code),
                    Leg(mode=FLIGHT, origin=hub_a.code, destination=hub_b.code),
                    Leg(mode=FLIGHT, origin=hub_b.code, destination=destination_code),
                ]))

    # Stage 3: train + fly (CKG-only currently)
    if include_train and origin_code == "CKG":
        for tc in get_train_connections_from("CKG-N"):
            train_arrival = tc.destination
            airport_to_fly_from = RAIL_TO_AIRPORT.get(train_arrival, train_arrival)

            # Skip if the train terminus *is* the destination (no flight needed)
            if airport_to_fly_from == destination_code:
                continue

            # Skip if airport-to-fly-from isn't a valid flight node
            if airport_to_fly_from not in NODES:
                continue
            if NODES[airport_to_fly_from].node_type not in {"airport", "both"}:
                continue

            train_leg = Leg(
                mode=TRAIN,
                origin="CKG-N",
                destination=train_arrival,
                duration_min=tc.duration_min,
                cost_cny=tc.cost_cny_2nd_class,
                notes=tc.notes,
            )

            # Direct flight from rail-airport to destination
            candidates.append(Itinerary(legs=[
                train_leg,
                Leg(mode=FLIGHT, origin=airport_to_fly_from, destination=destination_code),
            ]))

            # Longhaul extension: train + 1-stop flight for EUROPE / NORTH_AMERICA destinations
            # Only when max_stops >= 1 (train leg doesn't count as a flight stop).
            if max_stops >= 1 and destination.region in LONGHAUL_REGIONS:
                # Reuse the same transit-region rules used for pure-flight 1-stops,
                # but anchored on the airport we're flying out of after the train.
                rail_origin_region = NODES[airport_to_fly_from].region
                t_regions = _valid_transit_regions(rail_origin_region, destination.region)
                t_hubs = _airport_hubs_in_regions(
                    t_regions,
                    exclude={airport_to_fly_from, destination_code, origin_code},
                )
                for hub in t_hubs:
                    candidates.append(Itinerary(legs=[
                        train_leg,
                        Leg(mode=FLIGHT, origin=airport_to_fly_from, destination=hub.code),
                        Leg(mode=FLIGHT, origin=hub.code, destination=destination_code),
                    ]))

    return candidates
