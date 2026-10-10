"""Where a flyout opens. Reads the panel's published geometry (`/run/user/<uid>/carpatic-panel.json`) and falls back to the profile's bar sizes."""
import json, os

GAP = 8


def state_path():
    from . import config
    return os.path.join(config.runtime_dir(), "carpatic-panel.json")


def read_state():
    try: return json.load(open(state_path()))
    except (OSError, ValueError): return None


def anchor_for(mode, state):
    """-> (edge, (x, y, w, h)) of the panel item the flyout belongs to, or None."""
    if not state: return None
    want = {"quick": ("quick", "tray", "clock"), "calendar": ("clock", "quick"), "start": ("start", "search")}[mode]
    for s in state.get("surfaces", []):
        for k in want:
            r = s.get("items", {}).get(k)
            if r: return s["edge"], tuple(r)
    for s in state.get("surfaces", []):
        return s["edge"], (s["x"], s["y"], s["w"], s["h"])
    return None


def place(w, h, screen, edge, anchor, mode, align="auto"):
    """screen=(x,y,w,h). anchor=(x,y,w,h) in screen px. Returns (x, y). The flyout sits GAP px from the panel, aligned to the anchor and clamped on screen."""
    sx, sy, sw, sh = screen
    ax, ay, aw, ah = anchor
    if edge in ("bottom", "top"):
        if mode == "start" and align == "center": x = sx + (sw - w) // 2
        elif mode == "start": x = ax
        else: x = ax + aw - w if (ax + aw / 2) > sx + sw / 2 else ax
        y = ay - h - GAP if edge == "bottom" else ay + ah + GAP
    else:
        x = ax + aw + GAP if edge == "left" else ax - w - GAP
        y = ay + ah - h if edge == "left" and mode != "start" and (ay + ah / 2) > sy + sh / 2 else ay
        if mode == "start": y = sy + 40
    x = max(sx + GAP, min(x, sx + sw - w - GAP)); y = max(sy + GAP, min(y, sy + sh - h - GAP))
    return int(x), int(y)
