"""Small JSON state: fill mode, per-theme and light/dark choices, rotation, collections. One file, written atomically."""
import json, os, random as _random, time

from . import paths

FILL_MODES = [("fill", "Fill screen"), ("fit", "Fit to screen"), ("stretch", "Stretch to fill"), ("center", "Centre"), ("tile", "Tile")]
DEFAULT = {"fill": "fill", "per_theme": {}, "pair": {"enabled": False, "light": "", "dark": ""}, "monitors": {},
           "rotation": {"enabled": False, "every": 30, "collection": "carpatic-mode", "shuffle": True, "on_login": False, "last": 0, "order": [], "pos": 0},
           "collections": {}, "accent_from_wallpaper": False}

def _p(): return os.path.join(paths.wp_config_dir(), "state.json")

def load():
    try: d = json.load(open(_p()))
    except (OSError, ValueError): d = {}
    out = json.loads(json.dumps(DEFAULT))
    for k, v in d.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k not in ("per_theme", "monitors", "collections"): out[k].update(v)
        else: out[k] = v
    return out

def save(d):
    paths.ensure(os.path.dirname(_p()))
    tmp = _p() + f".{os.getpid()}.tmp"
    with open(tmp, "w") as f: json.dump(d, f, indent=1)
    os.replace(tmp, _p())

def update(fn):
    d = load(); fn(d); save(d); return d

# collections: user lists of picture paths. Virtual ones: carpatic-dark, carpatic-light, carpatic-mode (matches the theme), my-pictures, all
VIRTUAL = {"carpatic-mode": "Carpatic, matching dark/light", "carpatic-dark": "Carpatic (dark)", "carpatic-light": "Carpatic (light)",
           "my-pictures": "My pictures", "all": "Everything"}

def collection_paths(name, mode="dark", st=None):
    from . import library
    st = st or load()
    if name in st["collections"]: return [p for p in st["collections"][name] if os.path.isfile(p)]
    if name in ("carpatic-mode", "carpatic-dark", "carpatic-light"):
        m = mode if name == "carpatic-mode" else name.split("-")[1]
        return [i.path for i in library.builtin_items() if i.mode == m and i.group == "Carpathians"]
    if name == "my-pictures": return [i.path for i in library.local_items()]
    if name == "all": return [i.path for i in library.builtin_items()] + [i.path for i in library.local_items()]
    raise KeyError(name)

def collection_new(name):
    if not name or "/" in name or len(name) > 60 or name in VIRTUAL: raise ValueError("Pick a different name for the collection.")
    update(lambda d: d["collections"].setdefault(name, []))

def collection_add(name, path):
    def f(d):
        if name not in d["collections"]: raise KeyError(name)
        if path not in d["collections"][name]: d["collections"][name].append(path)
    update(f)

def collection_remove(name, path=None):
    def f(d):
        if name not in d["collections"]: raise KeyError(name)
        if path is None: del d["collections"][name]
        else: d["collections"][name] = [p for p in d["collections"][name] if p != path]
    update(f)

def next_in_rotation(st, mode, rng=_random, now=time.time):
    """Pick the next picture for rotation; keeps a shuffled order so nothing repeats until the list is used up. Mutates st['rotation']."""
    r = st["rotation"]
    pool = collection_paths(r["collection"], mode, st)
    if not pool: return None
    order = [p for p in r.get("order", []) if p in pool]
    pos = r.get("pos", 0)
    if not order or pos >= len(order) or set(order) != set(pool):
        order = pool[:]
        if r["shuffle"]: rng.shuffle(order)
        pos = 0
    pick = order[pos]
    r["order"], r["pos"], r["last"] = order, pos + 1, now()
    return pick
