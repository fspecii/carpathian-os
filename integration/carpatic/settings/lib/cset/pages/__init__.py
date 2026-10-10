"""Page registry: the order here is the order of the sidebar (Page.group separates the blocks)."""
import importlib

_MODULES = ["network", "sound", "appearance", "desktop", "animations", "display", "power", "input", "devices", "account", "system"]

def _load():
    out = []
    for m in _MODULES:
        try:
            mod = importlib.import_module(f"{__name__}.{m}")
        except ModuleNotFoundError as e:
            if e.name and e.name.endswith(f".{m}"): continue
            raise
        out.extend(getattr(mod, "PAGES", []))
    out.sort(key=lambda c: (c.group, c.order if hasattr(c, "order") else 0))
    return out

ALL = _load()
