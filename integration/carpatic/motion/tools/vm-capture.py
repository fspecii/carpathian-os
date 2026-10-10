#!/usr/bin/env python3
"""vm-capture.py MONITOR.sock OUTDIR SECONDS [--cmd 'shell command run on the host at t=0 (e.g. an ssh that starts the animation)'] : record the VM screen with
screendump as fast as the monitor answers (about 40-90 fps for a 1280x800 screen). Writes f<NNN>.ppm and times.txt (seconds since the command was started)."""
import os, socket, subprocess, sys, time
sock, out, secs = sys.argv[1], sys.argv[2], float(sys.argv[3]); cmd = sys.argv[sys.argv.index("--cmd") + 1] if "--cmd" in sys.argv else None
os.makedirs(out, exist_ok=True)
m = socket.socket(socket.AF_UNIX); m.connect(sock); m.settimeout(5); time.sleep(0.3)
try: m.recv(65536)
except OSError: pass
t0 = time.monotonic()
if cmd: subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
times = []; n = 0
while time.monotonic() - t0 < secs:
    ts = time.monotonic() - t0; f = os.path.abspath(os.path.join(out, "f%03d.ppm" % n))
    m.sendall(("screendump " + f + "\n").encode()); buf = b""
    while not buf.rstrip().endswith(b"(qemu)"):
        try: buf += m.recv(65536)
        except socket.timeout: break
    times.append(ts); n += 1
open(os.path.join(out, "times.txt"), "w").write("\n".join("%.3f" % t for t in times)); print("frames", n)
