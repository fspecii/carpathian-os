"""Where the wallpaper library keeps its files. Everything follows $HOME / XDG so tests can use a fake HOME."""
import os

def home():
    return os.environ.get("HOME") or os.path.expanduser("~")

def _xdg(var, default):
    v = os.environ.get(var)
    return v if v and os.path.isabs(v) else os.path.join(home(), default)

def config_dir():  # settings.conf of the desktop lives here too
    return os.environ.get("CARPATIC_CFG") or os.path.join(_xdg("XDG_CONFIG_HOME", ".config"), "carpatic")

def wp_config_dir():
    return os.path.join(config_dir(), "wallpapers")

def cache_dir():
    return os.path.join(_xdg("XDG_CACHE_HOME", ".cache"), "carpatic", "wallpapers")

def thumbs_dir():
    return os.path.join(cache_dir(), "thumbs")

def api_cache_dir():
    return os.path.join(cache_dir(), "api")

def pictures_dir():
    return os.path.join(home(), "Pictures", "Wallpapers")

def wallhaven_dir():
    return os.path.join(pictures_dir(), "Wallhaven")

def settings_conf():
    return os.path.join(config_dir(), "settings.conf")

def builtin_dirs():
    """Directories with the shipped Carpathian wallpapers (installed share, then the repo checkout)."""
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(os.path.join(here, "..", "..", ".."))
    cands = [os.environ.get("CARPATIC_WALLPAPER_DIR", ""),
             "/usr/local/share/carpatic/wallpapers", "/usr/share/carpatic/wallpapers",
             "/usr/local/share/carpatic/configurator/wallpapers",
             os.path.join(repo, "configurator", "share", "wallpapers"),
             os.path.join(repo, "design", "wallpapers")]
    return [d for d in cands if d and os.path.isdir(d)]

def theme_dirs():
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(os.path.join(here, "..", "..", ".."))
    cands = [os.environ.get("CARPATIC_THEMES", ""), "/usr/local/share/carpatic/configurator/themes",
             os.path.join(repo, "configurator", "themes"), os.path.join(config_dir(), "themes")]
    return [d for d in cands if d and os.path.isdir(d)]

def ensure(path, mode=0o755):
    os.makedirs(path, mode=mode, exist_ok=True)
    return path
