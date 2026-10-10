"""Loaded by carpatic-scale.pth at every Python start (site-packages). It does nothing until a program called carpatic-* (not the panel, which scales
itself) imports GTK3; then carpatic_scale.install() runs right after Gtk is loaded, so every Carpathian GTK app follows the display scale without each one
having to ask. See carpatic_scale.py."""
import os, sys

_SKIP = {"carpatic-panel", "carpatic-flyout", "carpatic-scale"}


def _wanted():
    a = os.path.basename(sys.argv[0]) if getattr(sys, "argv", None) and sys.argv[0] else ""
    if a in ("", "-c", "-m", "python3", "python"): return False
    return a.startswith("carpatic") and a not in _SKIP


class _Wrap:
    def __init__(self, loader): self._l = loader
    def create_module(self, spec): return self._l.create_module(spec)
    def exec_module(self, module):
        self._l.exec_module(module)
        try:
            for p in ("/usr/local/lib/carpatic", "/usr/lib/carpatic"):
                if os.path.isdir(p) and p not in sys.path: sys.path.append(p)
            import carpatic_scale
            carpatic_scale.install_for(os.path.basename(sys.argv[0]))
        except Exception:
            if os.environ.get("CARPATIC_SCALE_DEBUG"):
                import traceback; traceback.print_exc()


class _Finder:
    def find_spec(self, name, path=None, target=None):
        if name != "gi.repository.Gtk" or not _wanted(): return None
        sys.meta_path.remove(self)
        try:
            for f in sys.meta_path:
                fs = getattr(f, "find_spec", None)
                if fs is None: continue
                spec = fs(name, path, target)
                if spec is not None:
                    spec.loader = _Wrap(spec.loader)
                    return spec
        finally:
            pass
        return None


def arm():
    if os.environ.get("CARPATIC_UI_SCALE_OFF") != "1": sys.meta_path.insert(0, _Finder())


arm()
