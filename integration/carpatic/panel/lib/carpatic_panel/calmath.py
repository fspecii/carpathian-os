"""Calendar arithmetic: month grids, locale-aware first weekday, week numbers. Pure Python (datetime only), unit tested."""
import datetime as dt
import locale
import os

MON, SUN, SAT = 0, 6, 5
# Regions whose week starts on Sunday / Saturday (CLDR firstDay). Everything else starts on Monday.
_SUNDAY = set("US CA MX BR CO PE VE EC BO PY JP KR TW HK PH ID IN IL ZA KE NG GH ET AU NZ SG TH SA PA DO GT HN SV NI CR PR LA MO KH TT JM ZW ZM".split())
_SATURDAY = set("AE AF BH DJ DZ EG IQ IR JO KW LY OM QA SD SY".split())


def first_weekday_for(region):
    r = (region or "").upper()
    return SUN if r in _SUNDAY else SAT if r in _SATURDAY else MON


def system_first_weekday(setting="auto", env=None):
    """setting: auto | mon | sun | sat | 0..6. auto reads LC_TIME / LANG (de_DE.UTF-8 -> Monday, en_US -> Sunday)."""
    s = (setting or "auto").lower()
    table = {"mon": MON, "monday": MON, "sun": SUN, "sunday": SUN, "sat": SAT, "saturday": SAT}
    if s in table: return table[s]
    if s.isdigit(): return int(s) % 7
    use_locale = env is None
    env = os.environ if env is None else env
    loc = env.get("LC_TIME") or env.get("LC_ALL") or env.get("LANG") or ""
    if (not loc or loc in ("C", "POSIX")) and use_locale and not (env.get("LC_ALL") or env.get("LANG")):
        try: loc = locale.getlocale()[0] or ""
        except Exception: loc = ""
    region = ""
    base = loc.split(".")[0].split("@")[0]
    if "_" in base: region = base.split("_")[1]
    return first_weekday_for(region) if region else MON


def is_leap(y): return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def days_in_month(y, m):
    return 29 if m == 2 and is_leap(y) else [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]


def add_months(y, m, n):
    k = y * 12 + (m - 1) + n
    return k // 12, k % 12 + 1


def month_grid(y, m, first=MON, rows=6):
    """rows x 7 dates starting on the first-weekday on or before the 1st (6 rows keeps the popover height constant)."""
    first_day = dt.date(y, m, 1)
    start = first_day - dt.timedelta(days=(first_day.weekday() - first) % 7)
    return [[start + dt.timedelta(days=r * 7 + c) for c in range(7)] for r in range(rows)]


def weekday_names(first=MON, width="short"):
    base = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    names = base[first:] + base[:first]
    n = {"short": 3, "narrow": 1, "two": 2, "full": 0}[width]
    return [x if n == 0 else x[:n] for x in names]


def week_number(d, system="iso", first=MON):
    """ISO 8601 week (Europe) or US-style (week 1 contains Jan 1, weeks start on `first`)."""
    if system == "iso": return d.isocalendar()[1]
    jan1 = dt.date(d.year, 1, 1)
    start = jan1 - dt.timedelta(days=(jan1.weekday() - first) % 7)
    return (d - start).days // 7 + 1


def month_title(y, m):
    return dt.date(y, m, 1).strftime("%B %Y")


def clamp_day(y, m, d): return min(d, days_in_month(y, m))
