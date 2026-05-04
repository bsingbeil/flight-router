"""Probe the installed fli library's surface so we know what _real_fli_search needs."""
import importlib
import inspect

print("=== fli package version ===")
try:
    import fli  # noqa: F401
    print("fli imports OK")
except Exception as e:
    print(f"fli import FAILED: {e}")

print()
print("=== Modules expected by _real_fli_search ===")
for mod_name in ["fli.search", "fli.models"]:
    try:
        mod = importlib.import_module(mod_name)
        print(f"\n[{mod_name}] ✓")
        names = [n for n in dir(mod) if not n.startswith("_")]
        print("  exports:", ", ".join(sorted(names)))
    except Exception as e:
        print(f"\n[{mod_name}] ✗ {e}")

print()
print("=== Classes _real_fli_search relies on ===")
for path in [
    "fli.search.SearchFlights",
    "fli.models.FlightSearchFilters",
    "fli.models.FlightSegment",
    "fli.models.Airport",
    "fli.models.PassengerInfo",
    "fli.models.SeatType",
    "fli.models.MaxStops",
    "fli.models.SortBy",
]:
    mod_name, _, cls_name = path.rpartition(".")
    try:
        mod = importlib.import_module(mod_name)
        obj = getattr(mod, cls_name)
        print(f"  ✓ {path}  ({type(obj).__name__})")
    except Exception as e:
        print(f"  ✗ {path}  — {e}")

print()
print("=== Inspect SearchFlights.search signature ===")
try:
    from fli.search import SearchFlights
    sig = inspect.signature(SearchFlights.search)
    print("  SearchFlights.search", sig)
except Exception as e:
    print(f"  could not inspect: {e}")

print()
print("=== Inspect Airport (is it an Enum? a class?) ===")
try:
    from fli.models import Airport
    print(f"  type: {type(Airport).__name__}")
    sample = next(iter(Airport.__members__)) if hasattr(Airport, "__members__") else None
    if sample:
        print(f"  sample member: Airport.{sample}")
    else:
        print("  not enum-like — needs different access pattern")
except Exception as e:
    print(f"  could not inspect: {e}")
