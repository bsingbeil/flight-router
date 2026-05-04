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
