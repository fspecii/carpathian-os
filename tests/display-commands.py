#!/usr/bin/env python3
"""Standalone stdlib tests for integration/carpatic/compat/bin/carpatic-display.

Run from the repo root:  python3 tests/display-commands.py

The helper source is located relative to this test file's own repo root,
copied into a temporary directory and executed with sh. All xrandr traffic
goes to a fake stub (CARPATIC_XRANDR) that records argv and returns
scriptable exit codes; the stub dir is also prepended to PATH under the
name xrandr so a real xrandr can never be reached. XDG_CONFIG_HOME and
CARPATIC_LID_FILE point into the temp tree; HOME is inherited untouched.

These tests verify argument construction and exit-status propagation only.
They use fake commands and prove nothing about real hardware or hotplug
behaviour.

History note: the pre-fix helper always appended "--output $internal --off"
in the external branch, which collapsed to "--output --off" (empty operand)
when no internal screen was connected, and the final unconditional "exit 0"
swallowed xrandr failures. Both behaviours are asserted against here.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPER_SRC = ROOT / "integration" / "carpatic" / "compat" / "bin" / "carpatic-display"

ALLOWED_FLAGS = {
    "--output", "--off", "--auto", "--primary", "--pos", "--right-of", "--same-as",
}

QUERY_BOTH = """\
eDP-1 connected 1920x1080+0+0 (normal left inverted right) 344mm x 193mm
   1920x1080     60.00*+
HDMI-1 connected 1920x1080+1920+0 (normal left inverted right) 527mm x 297mm
   1920x1080     60.00*+
"""

# No internal output present at all (desktop box, or eDP-1 gone): this is the
# fixture that used to trigger "--output --off".
QUERY_EXTERNAL_ONLY_ONE = """\
HDMI-1 connected 1920x1080+0+0 (normal left inverted right) 527mm x 297mm
   1920x1080     60.00*+
"""

QUERY_EXTERNAL_ONLY_TWO = """\
HDMI-1 connected 1920x1080+0+0 (normal left inverted right) 527mm x 297mm
   1920x1080     60.00*+
DP-1 connected 1280x1024+1920+0 (normal left inverted right) 338mm x 270mm
   1280x1024     75.00*+
"""

QUERY_EXTERNAL_DISCONNECTED = """\
eDP-1 connected 1920x1080+0+0 (normal left inverted right) 344mm x 193mm
   1920x1080     60.00*+
HDMI-1 disconnected (normal left inverted right)
"""

STUB_XRANDR = """\
#!/bin/sh
# test stub: log argv, serve canned --query output, return canned statuses
printf 'CALL' >> "$XR_LOG"
for a in "$@"; do printf '%s\\037' "$a" >> "$XR_LOG"; done
printf '\\n' >> "$XR_LOG"
if [ "${1:-}" = "--query" ]; then
    [ -n "${XR_QUERY_FILE:-}" ] && cat "$XR_QUERY_FILE"
    exit "${XR_QUERY_RC:-0}"
fi
exit "${XR_APPLY_RC:-0}"
"""


class Case:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.cfg = tmp / "config"
        self.bin = tmp / "bin"
        self.helper = tmp / "helper" / "carpatic-display"
        self.lid = tmp / "lid" / "state"
        self.query_file = tmp / "query.txt"
        self.log = tmp / "xr.log"
        self.cfg.mkdir(parents=True)
        self.bin.mkdir(parents=True)
        (self.helper.parent).mkdir(parents=True)
        self.lid.parent.mkdir(parents=True)
        stub = self.bin / "xrandr"
        stub.write_text(STUB_XRANDR)
        stub.chmod(0o755)
        shutil.copy2(HELPER_SRC, self.helper)  # never execute the tree copy in place
        self.env = dict(os.environ)  # HOME is deliberately inherited untouched
        self.env["XDG_CONFIG_HOME"] = str(self.cfg)
        self.env["CARPATIC_XRANDR"] = str(stub)
        self.env["CARPATIC_LID_FILE"] = str(self.lid)
        self.env["XR_LOG"] = str(self.log)
        self.env["XR_QUERY_FILE"] = str(self.query_file)
        self.env["XR_APPLY_RC"] = "0"
        self.env["XR_QUERY_RC"] = "0"
        self.env["PATH"] = str(self.bin) + os.pathsep + self.env.get("PATH", "")
        # belt and braces: the xrandr on PATH inside the test env must be the stub
        assert shutil.which("xrandr", path=self.env["PATH"]) == str(stub)

    def set_lid(self, closed: bool):
        self.lid.write_text("State: %s\n" % ("closed" if closed else "open"))

    def set_query(self, text: str):
        self.query_file.write_text(text)

    def run(self, *argv: str):
        self.log.write_text("")
        proc = subprocess.run(
            ["sh", str(self.helper), *argv],
            env=self.env, capture_output=True, text=True, timeout=30,
        )
        return proc, self.calls()

    def calls(self):
        """Logged stub invocations as lists of argv strings."""
        out = []
        for line in self.log.read_text().splitlines():
            if line.startswith("CALL"):
                out.append([a for a in line[len("CALL"):].split("\x1f") if a != ""])
        return out


def applies(calls):
    """Only the non---query (layout) invocations."""
    return [c for c in calls if not (c and c[0] == "--query")]


def check_argv(calls, names, problems):
    """No empty/flag operand after --output; only known flags and output names. Only layout invocations are validated (--query probes are stub protocol)."""
    for argv in applies(calls):
        for i, a in enumerate(argv):
            if a in ("--output", "--right-of", "--same-as"):
                if i + 1 >= len(argv) or not argv[i + 1] or argv[i + 1].startswith("-"):
                    problems.append("empty/invalid operand after %s in %r" % (a, argv))
                elif a != "--output" and argv[i + 1] not in names:
                    problems.append("%s target %r is not a known output in %r"
                                    % (a, argv[i + 1], argv))
            elif a.startswith("-") and a not in ALLOWED_FLAGS:
                problems.append("unexpected flag %r in %r" % (a, argv))
            elif a == "--pos":
                if i + 1 >= len(argv) or not argv[i + 1].rstrip("0123456789x") == "":
                    problems.append("invalid --pos value in %r" % (argv,))


def shape(calls):
    """output name -> dict of the flags applied to it (for the single apply call)."""
    a = applies(calls)
    assert len(a) == 1, "expected exactly one layout invocation, got %r" % (a,)
    argv, out, cur = a[0], {}, None
    for i, arg in enumerate(argv):
        if arg == "--output":
            cur = argv[i + 1]
            out[cur] = {}
        elif arg in ("--right-of", "--same-as"):
            out[cur][arg] = argv[i + 1]
        elif arg in ("--off", "--auto", "--primary"):
            out[cur][arg] = True
        elif arg == "--pos":
            out[cur][arg] = argv[i + 1]
    return out


_failures = []


def check(label, cond, detail=""):
    if cond:
        print("PASS %s" % label)
    else:
        print("FAIL %s%s" % (label, (": " + detail) if detail else ""))
        _failures.append(label)


def expect(label, query, command, want_shape=None, want_off=(), want_rc=0,
           lid_closed=False, want_apply_count=1, query_rc=None, apply_rc=None):
    tmp = Path(tempfile.mkdtemp(prefix="carpatic-display-test-"))
    try:
        case = Case(tmp)
        case.set_query(query)
        case.set_lid(lid_closed)
        if query_rc is not None:
            case.env["XR_QUERY_RC"] = str(query_rc)
        if apply_rc is not None:
            case.env["XR_APPLY_RC"] = str(apply_rc)
        proc, calls = case.run(command)
        names = set()
        for line in query.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] in ("connected", "disconnected"):
                names.add(parts[0])
        problems = []
        check_argv(calls, names, problems)
        ok = proc.returncode == want_rc and not problems
        detail = "rc=%d (want %d) %s" % (proc.returncode, want_rc, "; ".join(problems))
        apps = applies(calls)
        if len(apps) != want_apply_count:
            ok, detail = False, "apply calls=%r want=%d" % (apps, want_apply_count)
        if ok and want_shape is not None:
            got = shape(calls)
            for out_name, want in want_shape.items():
                if got.get(out_name) != want:
                    ok = False
                    detail = "output %s: %r want %r (full: %r)" % (out_name, got.get(out_name), want, got)
        if ok and want_off:
            for out_name in want_off:
                if out_name not in got or got[out_name] != {"--off": True}:
                    ok, detail = False, "output %s not off: %r" % (out_name, got)
        check(label, ok, detail)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    if not HELPER_SRC.is_file():
        print("FAIL helper source missing: %s" % HELPER_SRC)
        return 1

    # 1. external-only, single output, no internal name in query at all
    #    (pre-fix this produced "--output --off")
    expect("external-only one output",
           QUERY_EXTERNAL_ONLY_ONE, "external",
           want_shape={"HDMI-1": {"--auto": True, "--primary": True, "--pos": "0x0"}},
           want_apply_count=1)

    # 2. external-only, two outputs: chain first->primary->0x0, second right-of first
    expect("external-only two outputs",
           QUERY_EXTERNAL_ONLY_TWO, "external",
           want_shape={"HDMI-1": {"--auto": True, "--primary": True, "--pos": "0x0"},
                       "DP-1": {"--auto": True, "--right-of": "HDMI-1"}})

    # 3. internal + external: external mode turns the laptop screen off
    expect("external with internal connected turns internal off",
           QUERY_BOTH, "external",
           want_shape={"HDMI-1": {"--auto": True, "--primary": True, "--pos": "0x0"}},
           want_off=("eDP-1",))

    # 4. mirror / extend / internal on the same fixture
    expect("mirror keeps internal primary, mirrors external",
           QUERY_BOTH, "mirror",
           want_shape={"eDP-1": {"--auto": True, "--primary": True, "--pos": "0x0"},
                       "HDMI-1": {"--auto": True, "--same-as": "eDP-1"}})
    expect("extend places external right-of internal",
           QUERY_BOTH, "extend",
           want_shape={"eDP-1": {"--auto": True, "--primary": True, "--pos": "0x0"},
                       "HDMI-1": {"--auto": True, "--right-of": "eDP-1"}})
    expect("internal turns external off",
           QUERY_BOTH, "internal",
           want_shape={"eDP-1": {"--auto": True, "--primary": True, "--pos": "0x0"}},
           want_off=("HDMI-1",))

    # 5. disconnected external falls back to the laptop screen
    expect("disconnected external falls back to internal",
           QUERY_EXTERNAL_DISCONNECTED, "extend",
           want_shape={"eDP-1": {"--auto": True, "--primary": True, "--pos": "0x0"}},
           want_off=("HDMI-1",))

    # 6. lid closed turns 'auto' (extend) into external-only
    expect("lid-closed extend uses external only",
           QUERY_BOTH, "auto",
           want_shape={"HDMI-1": {"--auto": True, "--primary": True, "--pos": "0x0"}},
           want_off=("eDP-1",), lid_closed=True)
    expect("lid-open auto stays extend",
           QUERY_BOTH, "auto",
           want_shape={"eDP-1": {"--auto": True, "--primary": True, "--pos": "0x0"},
                       "HDMI-1": {"--auto": True, "--right-of": "eDP-1"}},
           lid_closed=False)

    # 7. xrandr failures propagate (pre-fix the script always exited 0)
    expect("apply failure propagates nonzero (external)",
           QUERY_BOTH, "external", apply_rc=3, want_rc=3)
    expect("apply failure propagates nonzero (auto)",
           QUERY_BOTH, "auto", apply_rc=4, want_rc=4)
    expect("query failure dies nonzero",
           "", "extend", query_rc=1, want_rc=1, want_apply_count=0)

    print()
    if _failures:
        print("%d test(s) FAILED" % len(_failures))
        return 1
    print("all tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
