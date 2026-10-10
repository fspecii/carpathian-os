"""Window motion configuration and the session's owned compositor process."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

DEFAULTS = dict(enabled=True, style="macos", speed="normal", open=True, close=True,
                minimize=True, geometry=True, workspaces=True, menus=True)
BOOLS = {k for k, v in DEFAULTS.items() if isinstance(v, bool)}
CURVE = "cubic-bezier(0.22, 0.8, 0.25, 1.0)"

def config_dir():
    return Path(os.environ.get("CARPATIC_CONFIG") or
                str(Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "carpatic"))

def read_env(path):
    result = {}
    try:
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                result[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return result

def validate(key, value):
    if key in BOOLS:
        if isinstance(value, bool): return value
        if str(value).lower() in ("on", "true", "1"): return True
        if str(value).lower() in ("off", "false", "0"): return False
        raise ValueError(f"{key}: use on or off")
    if key == "style" and value in ("macos", "subtle"): return value
    if key == "speed" and value in ("slow", "normal", "fast"): return value
    raise ValueError(f"Invalid animation setting: {key}={value}")

def load():
    state = dict(DEFAULTS)
    try:
        raw = json.loads((config_dir() / "animations.json").read_text())
        if isinstance(raw, dict):
            for key, value in raw.items():
                if key in DEFAULTS:
                    try: state[key] = validate(key, value)
                    except ValueError: pass
    except (OSError, ValueError):
        pass
    cfg = config_dir()
    settings = read_env(cfg / "settings.conf")
    state["reduced"] = (settings.get("MOTION") == "reduced" or
                        (cfg / "reduced-motion").exists() or
                        os.environ.get("CARPATIC_NO_ANIM") == "1")
    try:
        state["reduced"] |= "carpatic.reduced-motion" in Path("/proc/cmdline").read_text().split()
    except OSError: pass
    return state

def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    try:
        tmp.write_text(content)
        tmp.chmod(0o600)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)

def save(state):
    atomic_write(config_dir() / "animations.json",
                 json.dumps({k: state[k] for k in DEFAULTS}, indent=2) + "\n")

def instant(triggers):
    return '{ triggers = ' + json.dumps(triggers) + '; }'

def timing(start, end, duration):
    return ('{ curve = "' + CURVE + '"; duration = ' + str(round(duration, 4)) +
            '; start = ' + json.dumps(start) + '; end = ' + json.dumps(end) + '; }')

def transform(trigger, start, end, duration, anchor_x, anchor_y, fade=True):
    # Use one screen-space affine transform. Separate root siblings still have
    # independent Picom timelines; a common X11 frame is required to keep native
    # chrome attached through interrupted transitions (FRAME-GROUPING-AUDIT.md).
    fields = [f'triggers = ["{trigger}"];',
              'user-scale = ' + timing(start, end, duration) + ';',
              'scale-x = "user-scale";', 'scale-y = "user-scale";',
              'shadow-scale-x = "user-scale";', 'shadow-scale-y = "user-scale";']
    for axis, anchor in (("x", anchor_x), ("y", anchor_y)):
        expr = f"({anchor} - window-{axis}) * (1 - user-scale)"
        fields += [f'offset-{axis} = "{expr}";', f'shadow-offset-{axis} = "{expr}";']
    opening = trigger in ("open", "show")
    target = 1
    fields.append('opacity = ' + (timing(0 if opening else target, target if opening else 0, duration)
                                  if fade else '1') + ';')
    fields.append('shadow-opacity = "opacity";')
    return "{ " + " ".join(fields) + " }"

def fade(trigger, duration):
    opening = trigger in ("open", "show")
    return '{ triggers = ["' + trigger + '"]; opacity = ' + timing(
        0 if opening else 1, 1 if opening else 0, duration) + '; shadow-opacity = "opacity"; }'

def geometry_transition(duration, saved_blend=True):
    fields = ['triggers = ["geometry"];', 'opacity = 1;']
    for axis, extent in (("x", "width"), ("y", "height")):
        fields.append(f'scale-{axis} = ' + timing(f'window-{extent}-before / window-{extent}', 1, duration) + ';')
        fields.append(f'offset-{axis} = ' + timing(f'window-{axis}-before - window-{axis}', 0, duration) + ';')
        fields += [f'shadow-scale-{axis} = "scale-{axis}";', f'shadow-offset-{axis} = "offset-{axis}";']
    # Blend into the freshly laid-out content quickly rather than keeping
    # differently sized text superimposed throughout the entire resize.
    if saved_blend:
        blend = min(.075, duration / 2)
        fields.append('saved-image-blend = { duration = ' + str(round(blend, 4)) +
                      '; delay = 0; start = 1; end = 0; };')
    return '{ ' + ' '.join(fields) + ' }'

def select_backend():
    """Avoid CPU GLX rasterization on virtual/software-only displays."""
    override = os.environ.get("CARPATIC_ANIMATION_BACKEND", "auto")
    if override in ("xrender", "glx"):
        return override
    if override != "auto":
        raise ValueError("Unsupported animation backend")
    if not session_guard():
        return "xrender"
    try:
        result = subprocess.run(["glxinfo", "-B"], capture_output=True, text=True,
                                timeout=3)
        if result.returncode == 0 and "Accelerated: yes" in result.stdout:
            return "glx"
    except (OSError, subprocess.SubprocessError):
        pass
    return "xrender"

def render(state, backend=None):
    backend = backend or os.environ.get("CARPATIC_ANIMATION_BACKEND", "xrender")
    if backend == "auto": backend = "xrender"
    if backend not in ("xrender", "glx"): raise ValueError("Unsupported animation backend")
    active = state["enabled"] and not state["reduced"]
    factor = {"slow": 1.5, "normal": 1.0, "fast": 0.65}[state["speed"]]
    cx = "window-monitor-x + window-monitor-width / 2"
    cy = "window-monitor-y + window-monitor-height / 2"
    panel = read_env(config_dir() / "panel.conf")
    position = panel.get("position", "auto")
    if position == "auto":
        position = {"ubuntu": "left", "minimal": "top"}.get(panel.get("design"), "bottom")
    tx, ty = cx, "window-monitor-y + window-monitor-height - 28"
    if position == "top": ty = "window-monitor-y + 28"
    if position in ("left", "right"):
        tx = "window-monitor-x + 28" if position == "left" else "window-monitor-x + window-monitor-width - 28"
        ty = cy
    def effect(key, trigger, seconds, start, end):
        if not active or not state[key]: return instant([trigger])
        if state["style"] == "subtle": return fade(trigger, seconds * factor)
        return transform(trigger, start, end, seconds * factor, cx, cy)
    normal = [effect("open", "open", .18, .96, 1), effect("close", "close", .13, 1, .96),
              effect("workspaces", "show", .16, .99, 1), effect("workspaces", "hide", .16, 1, .99)]
    # Keep the direct transform path on XRender, as in lightweight desktop
    # presets, without allocating/blending an additional saved window image.
    geometry = geometry_transition(.23 * factor, saved_blend=backend == "glx") if active and state["geometry"] else instant(["geometry"])
    normal.append(geometry)
    hide = (transform("hide", 1, .035, .30 * factor, tx, ty, fade=False) if state["style"] == "macos"
            else fade("hide", .17 * factor)) if active and state["minimize"] else instant(["hide"])
    show = (transform("show", .035, 1, .30 * factor, tx, ty, fade=False) if state["style"] == "macos"
            else fade("show", .17 * factor)) if active and state["minimize"] else instant(["show"])
    menus = []
    for trigger, seconds in (("open", .11), ("close", .09), ("show", .11), ("hide", .09)):
        if not active or not state["menus"]: menus.append(instant([trigger]))
        elif state["style"] == "subtle": menus.append(fade(trigger, seconds * factor))
        else:
            opening = trigger in ("open", "show")
            menus.append(transform(trigger, .98 if opening else 1, 1 if opening else .98,
                                   seconds * factor, "window-x + window-width / 2", "window-y"))
    all_instant = instant(["open", "close", "show", "hide", "geometry"])
    def rule(match, animations):
        return '{ match = ' + json.dumps(match) + '; animations = (' + ',\n'.join(animations) + '); }'
    # Picom's @ explicitly reads the discovered client, never the frame.
    # A native frame exists before client discovery and survives its teardown;
    # its own marker must select motion in both lifecycle intervals.
    rules = [rule("_CARPATIC_ANIMATION || _CARPATIC_ANIMATION@", normal),
             rule("_CARPATIC_ANIMATION = 1 || _CARPATIC_ANIMATION@ = 1", [hide]),
             rule("_CARPATIC_ANIMATION = 2 || _CARPATIC_ANIMATION@ = 2", [show]),
             rule("window_type *= 'menu' || window_type = 'tooltip' || window_type = 'notification'", menus),
             # Foreign GTK menus can have RGB popup parents despite the theme's
             # rounded 8px border. Clip that parent too, preserving menu motion.
             '{ match = ' + json.dumps("window_type *= 'menu'") + '; corner-radius = 8; }',
             rule("_CARPATIC_DRAGGING = 1 || _CARPATIC_DRAGGING@ = 1", [instant(["geometry"])]),
             rule("window_type = 'dock' || window_type = 'desktop' || class_g = 'i3lock' || class_g = 'slock' || name = 'Carpatic intro'", [all_instant])]
    # Picom 13 XRender partial repainting leaves stale exposed client regions
    # after animated occlusion (pixel regression reproduces this reliably).
    # Repaint the scene on damage events; this does not add an idle frame loop.
    damage = "false" if backend == "xrender" else "true"
    return ('# Generated by carpatic-animations.\nbackend = "' + backend + '";\nvsync = true;\n'
            'use-damage = ' + damage + ';\nunredir-if-possible = false;\nfading = false;\n'
            'shadow = false;\nanimations = (' + all_instant + ');\nrules = (\n' +
            ',\n'.join(rules) + '\n);\n')

def session_guard():
    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_CURRENT_DESKTOP") == "COSMIC":
        raise ValueError("Run window animations inside the Carpatic X11 desktop.")
    if not os.environ.get("DISPLAY"): return False
    if os.environ.get("CARPATIC_SESSION") != "1" and os.environ.get("XDG_CURRENT_DESKTOP") != "CarpaticRust":
        raise ValueError("Run window animations inside the Carpatic desktop.")
    return True

def runtime_dir():
    base = Path(os.environ.get("XDG_RUNTIME_DIR", f"/tmp/carpatic-runtime-{os.getuid()}"))
    display = ''.join(c if c.isalnum() else '_' for c in os.environ.get("DISPLAY", "offline"))
    return base / "window-animations" / display

def owned_pid():
    try:
        pid = int((runtime_dir() / "pid").read_text())
        proc = Path(f"/proc/{pid}")
        argv = proc.joinpath("cmdline").read_bytes().split(b"\0")
        expected = str(config_dir() / "window-animations.conf").encode()
        if proc.stat().st_uid == os.getuid() and argv and Path(os.fsdecode(argv[0])).name == "picom" and expected in argv:
            # A stale/reused PID record must not claim a compositor on another
            # display, even when that account uses the same config file there.
            display = b"DISPLAY=" + os.environ.get("DISPLAY", "").encode()
            if display in proc.joinpath("environ").read_bytes().split(b"\0"):
                return pid
    except (OSError, ValueError): pass
    return None

def signal_owned(pid, sig):
    """Signal the validated process; disappearance is a recoverable lifecycle race."""
    descriptor = None
    try:
        if hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
            descriptor = os.pidfd_open(pid)
        if owned_pid() != pid:
            return False
        if descriptor is not None:
            signal.pidfd_send_signal(descriptor, sig)
        else:
            os.kill(pid, sig)
        return True
    except ProcessLookupError:
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)

def prepare_minimise(delay):
    """Tell the WM whether to stage an unmap for the compositor's rule update."""
    import ctypes as c
    x = c.CDLL("libX11.so.6")
    x.XOpenDisplay.argtypes = [c.c_char_p]; x.XOpenDisplay.restype = c.c_void_p
    display = x.XOpenDisplay(None)
    if not display: raise ValueError("The desktop display is unavailable.")
    x.XDefaultRootWindow.argtypes = [c.c_void_p]; x.XDefaultRootWindow.restype = c.c_ulong
    x.XInternAtom.argtypes = [c.c_void_p, c.c_char_p, c.c_int]; x.XInternAtom.restype = c.c_ulong
    x.XChangeProperty.argtypes = [c.c_void_p, c.c_ulong, c.c_ulong, c.c_ulong,
                                 c.c_int, c.c_int, c.c_void_p, c.c_int]
    x.XCloseDisplay.argtypes = [c.c_void_p]
    atom = x.XInternAtom(display, b"_CARPATIC_ANIMATION_PREPARE", 0)
    value = c.c_ulong(delay)
    x.XChangeProperty(display, x.XDefaultRootWindow(display), atom, 6, 32, 0, c.byref(value), 1)
    x.XCloseDisplay(display)

def apply():
    if not session_guard():
        _apply()
        return
    runtime = runtime_dir()
    runtime.mkdir(parents=True, exist_ok=True)
    runtime.chmod(0o700)
    # Theme/panel and Settings updates can arrive together. Picom temporarily
    # tears down its signal watchers while reloading; serialize reloads so a
    # second SIGUSR1 cannot terminate it in that interval.
    with (runtime / "apply.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _apply()

def _apply():
    state = load()
    path = config_dir() / "window-animations.conf"
    content = render(state, select_backend() if state["enabled"] else "xrender")
    try: changed = path.read_text() != content
    except OSError: changed = True
    if changed: atomic_write(path, content)
    if not session_guard(): return
    delay = 50 if state["enabled"] and state["minimize"] and not state["reduced"] else 0
    pid = owned_pid()
    if not state["enabled"]:
        prepare_minimise(0)
        if pid:
            signal_owned(pid, signal.SIGTERM)
            end = time.monotonic() + 1
            while owned_pid() == pid and time.monotonic() < end: time.sleep(.02)
        return
    if pid:
        prepare_minimise(delay)
        if not changed: return
        signal_owned(pid, signal.SIGUSR1)
        time.sleep(.6)
        if owned_pid() == pid: return
        # Recover a compositor that failed while rebuilding its session.
    binary = shutil.which("picom")
    if not binary: raise ValueError("Window animation support is not installed.")
    version = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=5).stdout.strip().lstrip("v")
    try: supported = int(version.split(".", 1)[0].split("-", 1)[0]) >= 13
    except ValueError: supported = False
    if not supported: raise ValueError("Window animations require the updated Carpatic compositor.")
    runtime = runtime_dir(); runtime.mkdir(parents=True, exist_ok=True); runtime.chmod(0o700)
    with (runtime / "compositor.log").open("a") as log:
        process = subprocess.Popen([binary, "--config", str(config_dir() / "window-animations.conf")],
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    atomic_write(runtime / "pid", str(process.pid))
    time.sleep(.6)
    if process.poll() is not None:
        raise ValueError("Window animations could not start. See " + str(runtime / "compositor.log"))
    prepare_minimise(delay)

def main():
    parser = argparse.ArgumentParser(description="Configure Carpatic window animations")
    sub = parser.add_subparsers(dest="command")
    get = sub.add_parser("get"); get.add_argument("--json", action="store_true")
    setter = sub.add_parser("set"); setter.add_argument("key"); setter.add_argument("value"); setter.add_argument("--no-apply", action="store_true")
    sub.add_parser("apply"); sub.add_parser("render"); sub.add_parser("reset"); sub.add_parser("preview")
    args = parser.parse_args()
    try:
        if args.command in (None, "get"):
            state = load(); state["running"] = owned_pid() is not None
            print(json.dumps(state) if getattr(args, "json", False) else '\n'.join(f'{k}={v}' for k, v in state.items()))
        elif args.command == "render": print(render(load()), end="")
        elif args.command == "set":
            state = load(); state[args.key] = validate(args.key, args.value); save(state)
            if not args.no_apply: apply()
        elif args.command == "reset": save(DEFAULTS); apply()
        elif args.command == "apply": apply()
        elif args.command == "preview":
            if not session_guard(): raise ValueError("Open Preview from the Carpatic desktop.")
            from animation_preview import show
            show()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"carpatic-animations: {error}", file=sys.stderr); return 1
    return 0

if __name__ == "__main__": sys.exit(main())
