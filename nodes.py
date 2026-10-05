"""
nodes.py — airports and train stations relevant to routing.

A "node" is anywhere a journey can start, end, or transit. Most are airports,
but a few are HSR stations that are useful as alternative first-leg origins
from Chongqing (e.g. CKG-N, CKG-W, HKG-WK).

Region values:
  CHINA            mainland China (and HSR-reachable from CKG)
  GREATER_CHINA    Hong Kong, Taiwan
  EAST_ASIA        Korea, Japan
  SOUTHEAST_ASIA   Thailand, Singapore, Malaysia, Philippines, etc.
  MIDDLE_EAST      Gulf states, Turkey
  EUROPE           EU + UK
  NORTH_AMERICA    Canada + US
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Node:
    code: str               # IATA airport code, or rail code like "CKG-N"
    name: str               # display name
    city: str
    country: str
    region: str
    node_type: str          # "airport", "rail", or "both"
    is_hub: bool = True     # use as a connection point in routing?
    notes: Optional[str] = None


# Master node list, keyed by code.  Lookup: NODES["HKG"]
NODES: dict[str, Node] = {

    # ===== CHINA — airports =====
    "CKG": Node("CKG", "Chongqing Jiangbei International", "Chongqing", "China",
                "CHINA", "airport",
                notes="Home base. Decent international service, growing."),
    "CTU": Node("CTU", "Chengdu Tianfu International", "Chengdu", "China",
                "CHINA", "airport"),
    "PEK": Node("PEK", "Beijing Capital", "Beijing", "China", "CHINA", "airport"),
    "PKX": Node("PKX", "Beijing Daxing", "Beijing", "China", "CHINA", "airport"),
    "PVG": Node("PVG", "Shanghai Pudong", "Shanghai", "China", "CHINA", "airport"),
    "SHA": Node("SHA", "Shanghai Hongqiao", "Shanghai", "China", "CHINA", "airport",
                notes="Mostly domestic. Hongqiao = HSR-connected."),
    "CAN": Node("CAN", "Guangzhou Baiyun", "Guangzhou", "China", "CHINA", "airport"),
    "SZX": Node("SZX", "Shenzhen Bao'an", "Shenzhen", "China", "CHINA", "airport"),
    "KMG": Node("KMG", "Kunming Changshui", "Kunming", "China", "CHINA", "airport"),
    "XIY": Node("XIY", "Xi'an Xianyang", "Xi'an", "China", "CHINA", "airport"),
    "XMN": Node("XMN", "Xiamen Gaoqi", "Xiamen", "China", "CHINA", "airport"),

    # ===== CHINA — train stations =====
    # Some cities have both an airport and a useful HSR endpoint; modeled as
    # separate nodes so the candidate generator can choose either.
    "CKG-N": Node("CKG-N", "Chongqing North Railway Station", "Chongqing",
                  "China", "CHINA", "rail",
                  notes="HSR origin. Short metro from city center."),
    "CKG-W": Node("CKG-W", "Chongqing West Railway Station", "Chongqing",
                  "China", "CHINA", "rail",
                  notes="HSR origin for most fast trains south/east (Guangzhou, Shenzhen, "
                        "Hong Kong, Kunming, Shanghai). Metro Line 5 / Loop Line."),
    "HKG-WK": Node("HKG-WK", "Hong Kong West Kowloon", "Hong Kong", "Hong Kong",
                   "GREATER_CHINA", "rail",
                   notes="HSR terminus. ~30-40min to HKG airport via taxi/MTR."),

    # ===== GREATER CHINA =====
    "HKG": Node("HKG", "Hong Kong International", "Hong Kong", "Hong Kong",
                "GREATER_CHINA", "airport"),
    "TPE": Node("TPE", "Taipei Taoyuan", "Taipei", "Taiwan",
                "GREATER_CHINA", "airport"),

    # ===== EAST ASIA =====
    "ICN": Node("ICN", "Seoul Incheon", "Seoul", "South Korea",
                "EAST_ASIA", "airport"),
    "NRT": Node("NRT", "Tokyo Narita", "Tokyo", "Japan", "EAST_ASIA", "airport"),
    "HND": Node("HND", "Tokyo Haneda", "Tokyo", "Japan", "EAST_ASIA", "airport"),

    # ===== SOUTHEAST ASIA =====
    "BKK": Node("BKK", "Bangkok Suvarnabhumi", "Bangkok", "Thailand",
                "SOUTHEAST_ASIA", "airport"),
    "SIN": Node("SIN", "Singapore Changi", "Singapore", "Singapore",
                "SOUTHEAST_ASIA", "airport"),
    "KUL": Node("KUL", "Kuala Lumpur International", "Kuala Lumpur", "Malaysia",
                "SOUTHEAST_ASIA", "airport"),
    "MNL": Node("MNL", "Manila Ninoy Aquino", "Manila", "Philippines",
                "SOUTHEAST_ASIA", "airport"),
    "SGN": Node("SGN", "Ho Chi Minh City Tan Son Nhat", "Ho Chi Minh City",
                "Vietnam", "SOUTHEAST_ASIA", "airport",
                notes="Main Vietnamese international hub."),
    "HAN": Node("HAN", "Hanoi Noi Bai", "Hanoi", "Vietnam",
                "SOUTHEAST_ASIA", "airport",
                notes="Northern Vietnam hub; useful for connections "
                      "to/from southern China."),
    "DAD": Node("DAD", "Da Nang International", "Da Nang", "Vietnam",
                "SOUTHEAST_ASIA", "airport", is_hub=False,
                notes="Limited international service. Useful as origin/destination, "
                      "rarely as transit point."),

    # ===== MIDDLE EAST =====
    "DOH": Node("DOH", "Doha Hamad", "Doha", "Qatar", "MIDDLE_EAST", "airport"),
    "DXB": Node("DXB", "Dubai International", "Dubai", "UAE",
                "MIDDLE_EAST", "airport"),
    "AUH": Node("AUH", "Abu Dhabi International", "Abu Dhabi", "UAE",
                "MIDDLE_EAST", "airport"),
    "IST": Node("IST", "Istanbul Airport", "Istanbul", "Turkey",
                "MIDDLE_EAST", "airport"),

    # ===== EUROPE =====
    "LHR": Node("LHR", "London Heathrow", "London", "UK", "EUROPE", "airport"),
    "CDG": Node("CDG", "Paris Charles de Gaulle", "Paris", "France",
                "EUROPE", "airport"),
    "FRA": Node("FRA", "Frankfurt", "Frankfurt", "Germany", "EUROPE", "airport"),
    "AMS": Node("AMS", "Amsterdam Schiphol", "Amsterdam", "Netherlands",
                "EUROPE", "airport"),
    "MUC": Node("MUC", "Munich", "Munich", "Germany", "EUROPE", "airport"),
    "VIE": Node("VIE", "Vienna International", "Vienna", "Austria",
                "EUROPE", "airport",
                notes="Austrian Airlines hub. Tight Lufthansa Group "
                      "integration with MUC and FRA."),

    # ===== NORTH AMERICA =====
    "YVR": Node("YVR", "Vancouver International", "Vancouver", "Canada",
                "NORTH_AMERICA", "airport"),
    "YYZ": Node("YYZ", "Toronto Pearson", "Toronto", "Canada",
                "NORTH_AMERICA", "airport"),
    "YEG": Node("YEG", "Edmonton International", "Edmonton", "Canada",
                "NORTH_AMERICA", "airport"),
    "SEA": Node("SEA", "Seattle-Tacoma", "Seattle", "USA",
                "NORTH_AMERICA", "airport"),
    "SFO": Node("SFO", "San Francisco International", "San Francisco", "USA",
                "NORTH_AMERICA", "airport"),
    "LAX": Node("LAX", "Los Angeles International", "Los Angeles", "USA",
                "NORTH_AMERICA", "airport"),
    "ORD": Node("ORD", "Chicago O'Hare", "Chicago", "USA",
                "NORTH_AMERICA", "airport"),
}


# ---------- Helpers ----------

def get_node(code: str) -> Node:
    """Look up a node by code. Raises KeyError if not found."""
    return NODES[code]


def get_hubs_in_region(region: str) -> list[Node]:
    """All hub nodes in a given region."""
    return [n for n in NODES.values() if n.region == region and n.is_hub]


def get_airports_in_region(region: str) -> list[Node]:
    """Hub airports only (no rail nodes)."""
    return [n for n in NODES.values()
            if n.region == region and n.is_hub and n.node_type == "airport"]
