#!/usr/bin/env python3
"""Guest-only desktop diagnostics; no credentials or command-line arguments logged."""
import json, os, time
from pathlib import Path
TARGETS = {'picom', 'carpatic-wm', 'Xorg', 'python3', 'xterm', 'st', 'dwm'}
previous = {}; last = time.monotonic(); hz = os.sysconf('SC_CLK_TCK')
while True:
    now = time.monotonic(); elapsed = now - last; rows = []; current = {}
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit(): continue
        try:
            text = (proc / 'stat').read_text(); name = text[text.index('(')+1:text.rindex(')')]
            if name not in TARGETS: continue
            role = name
            if name == 'python3':
                argv = (proc/'cmdline').read_bytes().split(b'\0')
                if len(argv) > 1 and argv[1].startswith(b'/'):
                    role = Path(os.fsdecode(argv[1])).name
            values = text[text.rindex(')')+2:].split(); ticks = int(values[11]) + int(values[12])
            pid = int(proc.name); current[pid] = ticks
            rows.append(dict(pid=pid, name=name, role=role, state=values[0],
                             cpu_percent=round(100*(ticks-previous.get(pid,ticks))/hz/max(elapsed,.001),2),
                             rss_kib=int(values[21])*os.sysconf('SC_PAGE_SIZE')//1024,
                             wait=(proc/'wchan').read_text().strip()))
        except (OSError, ValueError, IndexError): continue
    memory = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        if key in ('MemAvailable', 'MemTotal', 'SwapFree', 'SwapTotal'): memory[key] = int(value.split()[0])
    print(json.dumps(dict(time=time.time(), processes=rows, memory_kib=memory)), flush=True)
    previous = current; last = now; time.sleep(1)
