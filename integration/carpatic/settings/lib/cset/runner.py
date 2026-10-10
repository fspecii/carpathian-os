"""Run long commands (pack installs, updates, language engines) with live progress and without ever opening a terminal.
GTK-free: parsing, elevation choice and the streaming runner; the sheet that shows it is ui.ProgressSheet.
Elevation follows the rest of Carpathian OS (geek/bin/carpatic-sudo): root runs directly; with a polkit agent running pkexec asks in the agent's own dialog;
otherwise doas/sudo is used and Settings asks for the password in its own styled dialog (fed to a pty, never put on a command line or stored)."""
import os, re, pty, select, shutil, signal, subprocess, time
from . import sysutil as su

PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
APK = re.compile(r"\((\d+)/(\d+)\)\s+(Installing|Upgrading|Purging|Downloading)\s+(\S+)")
PROG = re.compile(r"^progress:\s*(?:(\d{1,3})\s+)?(.*)$")
AUTH_FAIL = re.compile(r"(Authentication failed|Sorry, try again|incorrect password|Permission denied|is not in the sudoers|not allowed)", re.I)

def parse_progress(line):
    """one output line -> (fraction or None, text or None). fraction is 0..1 for the current step"""
    line = line.strip()
    if not line: return None, None
    m = APK.search(line)
    if m: return int(m.group(1)) / max(1, int(m.group(2))), f"{m.group(3)} {m.group(4)}"
    m = PROG.match(line)
    if m: return (int(m.group(1)) / 100 if m.group(1) else None), (m.group(2) or None)
    m = PCT.search(line)
    if m:
        v = float(m.group(1))
        if 0 <= v <= 100: return v / 100, None
    return None, line[:90]

def polkit_agent_running():
    if os.environ.get("CSET_FAKE_POLKIT"): return True   # tests
    return bool(su.out("pgrep", "-f", "polkit-gnome-authentication-agent|polkit-mate-authentication-agent|lxqt-policykit-agent|polkit-kde-authentication-agent|polkit-agent|polkit-gnome-agent"))

def elevation():
    """-> ('root'|'pkexec'|'doas'|'sudo'|None, prefix list)"""
    if os.geteuid() == 0: return "root", []
    if shutil.which("pkexec") and os.environ.get("DISPLAY") and polkit_agent_running(): return "pkexec", ["pkexec"]
    for t in ("doas", "sudo"):
        if shutil.which(t): return t, [t]
    if shutil.which("pkexec") and os.environ.get("DISPLAY"): return "pkexec", ["pkexec"]
    return None, []

def friendly_error(rc, tail):
    if rc in (126, 127) and not tail.strip(): return "The password window was closed, so nothing was changed."
    t = (tail or "").lower()
    if "checksum mismatch" in t: return "The download was damaged on the way. Try again in a moment."
    if "download failed" in t or "could not resolve" in t or "network" in t or "curl" in t: return "The download did not work. Check your internet connection and try again."
    if "not authorized" in t or "dismissed" in t or rc in (126,): return "The password window was closed, so nothing was changed."
    if "no space" in t: return "Your disk is full. Free up some space and try again."
    if "needs administrator rights" in t: return "This needs your administrator password."
    return "That did not finish. Nothing broken was left behind; you can try again."

class Job:
    """one command; run() blocks (call it from a thread). on_line(str) gets every output line (split on \\n and \\r). cancel() stops it."""
    def __init__(self, cmd, env=None, password=None):
        self.cmd, self.env, self.password = list(cmd), env or {}, password; self.proc = None; self.pid = None; self.cancelled = False; self.tail = []; self.auth_failed = False
    def cancel(self):
        self.cancelled = True
        try:   # the whole group: a shell's children keep the output pipe open otherwise
            pid = self.proc.pid if self.proc else self.pid
            if pid: os.killpg(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError): pass
    def _emit(self, raw, on_line):
        for ln in re.split(r"[\r\n]", raw):
            if ln.strip():
                self.tail.append(ln.strip()); self.tail = self.tail[-40:]
                if self.password is not None and AUTH_FAIL.search(ln): self.auth_failed = True
                if on_line: on_line(ln)
    def run(self, on_line=None):
        if su.DRY:
            su._log_dry(self.cmd)
            if on_line: on_line("progress: 50 Working"); on_line("progress: 100 Done")
            return 0
        env = dict(os.environ); env.update(self.env); env.setdefault("LC_ALL", "C")
        if self.password is not None: return self._run_pty(env, on_line)
        try: self.proc = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env, start_new_session=True)
        except FileNotFoundError: self.tail.append("not installed"); return 127
        buf = b""
        while True:
            chunk = self.proc.stdout.read1(4096) if hasattr(self.proc.stdout, "read1") else self.proc.stdout.read(1)
            if not chunk: break
            buf += chunk; parts = re.split(rb"[\r\n]", buf); buf = parts.pop()
            for p in parts: self._emit(p.decode("utf-8", "replace"), on_line)
        if buf.strip(): self._emit(buf.decode("utf-8", "replace"), on_line)
        return self.proc.wait()
    def _run_pty(self, env, on_line):
        pid, fd = pty.fork()
        if pid == 0:
            try: os.execvpe(self.cmd[0], self.cmd, env)
            finally: os._exit(127)
        self.pid = pid; buf = b""; sent = False
        while True:
            try:
                r, _, _ = select.select([fd], [], [], 5)
                if not r: continue
                data = os.read(fd, 4096)
            except OSError: break
            if not data: break
            buf += data
            if not sent and re.search(rb"[Pp]assword.*:\s*$", buf):
                os.write(fd, (self.password + "\n").encode()); sent = True; buf = b""; continue
            parts = re.split(rb"[\r\n]", buf); buf = parts.pop()
            for p in parts: self._emit(p.decode("utf-8", "replace"), on_line)
        if buf.strip(): self._emit(buf.decode("utf-8", "replace"), on_line)
        _, status = os.waitpid(pid, 0)
        return os.waitstatus_to_exitcode(status)

def pack_command(pack_id, kind, binary=None):
    """command to install one pack; apk packs need root (elevation is added by the caller)"""
    return [binary or shutil.which("carpatic-pack") or "carpatic-pack", "install", pack_id], kind == "apk"
