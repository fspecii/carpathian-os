"""Flyout timing uses the desktop's animation preferences without launching tools."""
import importlib.util
from pathlib import Path


def slide_duration(requested=True):
    if not requested:
        return 0.0
    candidates = [Path('/usr/local/share/carpatic/motion/window_animations.py'),
                  Path(__file__).resolve().parents[3] / 'motion/lib/window_animations.py']
    for path in candidates:
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location('carpatic_flyout_motion', path)
        controller = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(controller)
        state = controller.load()
        if not state['enabled'] or state['reduced'] or not state['menus']:
            return 0.0
        return .11 * {'slow': 1.5, 'normal': 1.0, 'fast': .65}[state['speed']]
    return .11
