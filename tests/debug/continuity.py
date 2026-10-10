#!/usr/bin/env python3
"""Visible client/chrome seam oracle on isolated Xorg; not a presentation clock."""
import json
import ctypes as c
import os
import re
from pathlib import Path
import subprocess
import sys
import time

if (os.environ.get('CARPATIC_VM_TEST') != '1' or not Path('/etc/alpine-release').exists()
        or os.environ.get('DISPLAY') != ':0' or 'WAYLAND_DISPLAY' in os.environ):
    raise SystemExit('Explicit isolated Alpine Xorg :0 only')
if subprocess.run(['pgrep', '-x', 'i3lock'], stdout=subprocess.DEVNULL).returncode == 0:
    raise SystemExit('Fixture is locked')
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk
from rendering import Display, COLOR, command

root = Gdk.get_default_root_window()
records = []
errors = []
x = Display()
x.x.XMoveResizeWindow.argtypes=[c.c_void_p,c.c_ulong,c.c_int,c.c_int,c.c_uint,c.c_uint]
x.x.XMoveResizeWindow.restype=c.c_int
x.x.XFlush.argtypes=[c.c_void_p]; x.x.XFlush.restype=c.c_int

def request(w,target):
    stamp=time.monotonic()
    x.x.XMoveResizeWindow(x.handle,w,*map(int,target)); x.x.XFlush(x.handle)
    return stamp
window = None
terminal = None
cfg = Path.home()/'.config/carpatic'
paths = [cfg/'animations.json', cfg/'reduced-motion']
saved = {p:p.read_bytes() if p.exists() else None for p in paths}
original_backend = os.environ.get('CARPATIC_ANIMATION_BACKEND')

def pump():
    while Gtk.events_pending(): Gtk.main_iteration_do(False)

def column():
    pump()
    pix = Gdk.pixbuf_get_from_window(root, 600, 40, 1, 680)
    if pix is None: raise RuntimeError('No root capture')
    data = pix.get_pixels(); stride = pix.get_rowstride()
    return [tuple(data[y*stride:y*stride+3]) for y in range(680)]

def near(a,b): return max(abs(a[i]-b[i]) for i in range(3)) <= 8

def geometry(w):
    return dict(line.split('=',1) for line in command('xdotool','getwindowgeometry','--shell',str(w)).splitlines() if '=' in line)

try:
    for backend in ('glx','xrender'):
        os.environ['CARPATIC_ANIMATION_BACKEND'] = backend
        state=json.loads(command('carpatic-animations','get','--json'))
        state.update(enabled=True,reduced=False,geometry=True,style='macos',speed='slow')
        paths[0].write_text(json.dumps(state)); paths[1].unlink(missing_ok=True)
        command('carpatic-animations','apply')
        active=json.loads(command('carpatic-animations','get','--json'))
        if not active['running'] or active['reduced'] or not active['geometry']:
            raise AssertionError('Full geometry animations must be active')
        for kind in ('x11','gtk','terminal'):
            if kind == 'x11':
                w=x.create('Continuity marker',COLOR,500,250)
                x.x.XMapWindow(x.handle,w); x.sync()
            elif kind == 'gtk':
                window=Gtk.Window(title='GTK continuity marker')
                window.set_type_hint(Gdk.WindowTypeHint.DIALOG)
                area=Gtk.DrawingArea(); area.set_size_request(500,250)
                def draw(_widget,cr):
                    cr.set_source_rgb(0x25/255,0xa9/255,0xdf/255); cr.paint()
                area.connect('draw',draw); window.add(area); window.show_all(); pump()
                w=window.get_window().get_xid()
            else:
                terminal=subprocess.Popen(['xterm','-T','Terminal continuity marker','-bg','#25a9df','-fg','#25a9df','-e','sh','-c','sleep 60'])
                time.sleep(.5)
                w=int(command('xdotool','search','--name','^Terminal continuity marker$').splitlines()[-1])
                command('xdotool','windowactivate','--sync',str(w))
                command('xdotool','key','super+shift+space')
                if '= 1' not in command('xprop','-id',str(w),'_CARPATIC_FLOATING'):
                    raise AssertionError('Terminal fixture must be floating')
            command('xdotool','windowactivate','--sync',str(w))
            command('xdotool','windowsize',str(w),'600','270')
            command('xdotool','windowmove',str(w),'250','180')
            time.sleep(.6); pump()
            g=geometry(w); top=int(g['Y'])-40
            baseline=column(); chrome=baseline[top-8]
            blue=(0x25,0xa9,0xdf)
            if not near(baseline[top+40],blue): raise AssertionError((kind,'Marker not visible',g,baseline[top+40]))
            if near(chrome,blue): raise AssertionError('Cannot distinguish native chrome')
            if kind=='x11':
                # Fault control: hide only this fixture's real native decoration.
                chrome_id=None
                for candidate in re.findall(r'^\s+(0x[0-9a-f]+)',command('xwininfo','-root','-tree'),re.M):
                    association=command('xprop','-id',candidate,'_CARPATIC_CLIENT')
                    found=re.search(r'window id # (0x[0-9a-f]+)',association)
                    if found and int(found.group(1),16)==w:
                        chrome_id=candidate; break
                if chrome_id is None: raise AssertionError('No associated native decoration')
                try:
                    command('xdotool','windowunmap',chrome_id); time.sleep(.5)
                    fault=column()
                    matching=[i for i in range(max(0,top-70),top) if near(fault[i],chrome)]
                    gap=top-max(matching)-1 if matching else 999
                    if gap<=4: raise AssertionError('Oracle failed to detect missing chrome')
                    print(json.dumps(dict(negative_control=backend,detected_gap=gap)),flush=True)
                finally:
                    command('xdotool','windowmap',chrome_id); time.sleep(.5)
            for cycle in range(4):
                for target in (('300','320','650','310'),('250','180','600','270')):
                    start=request(w,target)
                    sampled=0; missed=0; interrupted=False; reversed_at=None
                    while time.monotonic()-start < .50:
                        if not interrupted and time.monotonic()-start >= .09:
                            interrupted=True
                            reverse=('250','180','600','270') if target[0]=='300' else ('300','320','650','310')
                            reversed_at=request(w,reverse)-start
                        capture_begin=time.monotonic(); pixels=column(); capture_end=time.monotonic()
                        rows=[i for i,p in enumerate(pixels) if near(p,blue)]
                        # Require a body run, preventing isolated unrelated pixels from qualifying.
                        body=[i for i in rows if i+15 < len(pixels) and near(pixels[i+15],blue)]
                        if body:
                            edge=body[0]
                            chrome_rows=[i for i in range(max(0,edge-70),edge) if near(pixels[i],chrome)]
                            gap=edge-max(chrome_rows)-1 if chrome_rows else 999
                            item=dict(backend=backend,client=kind,cycle=cycle,target=target,t=round(capture_end-start,4),capture_begin=round(capture_begin-start,4),capture_ms=round((capture_end-capture_begin)*1000,3),reverse_t=round(reversed_at,4) if reversed_at is not None else None,body_top=edge+40,gap=gap)
                            records.append(item); sampled+=1
                            if gap>4:
                                errors.append(item)
                                if len(errors)<=6:
                                    Gdk.pixbuf_get_from_window(root,0,0,1360,768).savev(f'/var/tmp/continuity-failure-{len(errors)}.png','png',[],[])
                        else:
                            missed+=1
                            if missed==1:
                                Gdk.pixbuf_get_from_window(root,0,0,1360,768).savev('/var/tmp/continuity-missing.png','png',[],[])
                        time.sleep(.008)
                    if sampled<3: raise AssertionError(dict(reason='Insufficient visible samples',backend=backend,client=kind,cycle=cycle,target=target,sampled=sampled,missing=missed,elapsed=time.monotonic()-start,geometry=geometry(w)))
            case_records=[r for r in records if r['backend']==backend and r['client']==kind]
            span=max(r['body_top'] for r in case_records)-min(r['body_top'] for r in case_records)
            if span<12: raise AssertionError('No visible transition coverage')
            if kind=='x11': x.destroy(w)
            elif kind=='gtk': window.destroy(); window=None; pump()
            else: terminal.terminate(); terminal.wait(timeout=5); terminal=None
            print(json.dumps(dict(case=f'{backend}-{kind}',samples=sum(r['backend']==backend and r['client']==kind for r in records),failed=sum(r['backend']==backend and r['client']==kind for r in errors))),flush=True)
    print(json.dumps(dict(summary=True,samples=len(records),failed=len(errors),scope='Xorg root samples, not physical presentation timing')),flush=True)
    Path('/var/tmp/continuity-records.json').write_text(json.dumps(records))
    sys.exit(bool(errors))
finally:
    Path('/var/tmp/continuity-records.json').write_text(json.dumps(records))
    if window: window.destroy()
    if terminal: terminal.terminate(); terminal.wait(timeout=5)
    x.close()
    for path,data in saved.items():
        if data is None: path.unlink(missing_ok=True)
        else: path.write_bytes(data)
    if original_backend is None: os.environ.pop('CARPATIC_ANIMATION_BACKEND',None)
    else: os.environ['CARPATIC_ANIMATION_BACKEND']=original_backend
    command('carpatic-animations','apply')
