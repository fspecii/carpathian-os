#!/usr/bin/env python3
"""Separate direct ConfigureRequest acknowledgement from root-capture overhead.

Not a physical frame clock. Run only on explicitly isolated Alpine Xorg.
"""
import ctypes as c
import json
import os
from pathlib import Path
import statistics
import sys
import time

if (os.environ.get('CARPATIC_VM_TEST') != '1' or not Path('/etc/alpine-release').exists()
        or os.environ.get('DISPLAY') != ':0' or 'WAYLAND_DISPLAY' in os.environ):
    raise SystemExit('Explicit isolated Alpine Xorg :0 only')
import gi
gi.require_version('Gdk','3.0')
from gi.repository import Gdk
from rendering import Display, COLOR, command

x=Display()
for name,result,args in [
    ('XMoveWindow',c.c_int,[c.c_void_p,c.c_ulong,c.c_int,c.c_int]),
    ('XFlush',c.c_int,[c.c_void_p]),
    ('XGetGeometry',c.c_int,[c.c_void_p,c.c_ulong,c.POINTER(c.c_ulong),c.POINTER(c.c_int),c.POINTER(c.c_int),c.POINTER(c.c_uint),c.POINTER(c.c_uint),c.POINTER(c.c_uint),c.POINTER(c.c_uint)])]:
    method=getattr(x.x,name); method.restype=result; method.argtypes=args

def geometry(w):
    root=c.c_ulong(); gx=c.c_int(); gy=c.c_int()
    width=c.c_uint(); height=c.c_uint(); border=c.c_uint(); depth=c.c_uint()
    if not x.x.XGetGeometry(x.handle,w,c.byref(root),c.byref(gx),c.byref(gy),c.byref(width),c.byref(height),c.byref(border),c.byref(depth)):
        raise RuntimeError('Geometry query failed')
    return gx.value,gy.value,width.value,height.value

root=Gdk.get_default_root_window()
paths=[Path.home()/'.config/carpatic'/name for name in ['animations.json','reduced-motion']]
saved={p:p.read_bytes() if p.exists() else None for p in paths}
backend_env=os.environ.get('CARPATIC_ANIMATION_BACKEND')
records=[]
try:
    for backend in ['glx','xrender']:
        os.environ['CARPATIC_ANIMATION_BACKEND']=backend
        settings=json.loads(command('carpatic-animations','get','--json'))
        settings.update(enabled=True,reduced=False,geometry=True,style='macos',speed='slow')
        paths[0].write_text(json.dumps(settings));paths[1].unlink(missing_ok=True)
        command('carpatic-animations','apply')
        w=x.create('Direct motion timing marker',COLOR,600,270)
        x.x.XMapWindow(x.handle,w);x.sync()
        command('xdotool','windowactivate','--sync',str(w))
        for mode in ['geometry-only','capture']:
            for cycle in range(6):
                x.x.XMoveWindow(x.handle,w,250,180);x.x.XFlush(x.handle)
                time.sleep(.55)
                before=geometry(w)
                x.x.XMoveWindow(x.handle,w,300,320);x.x.XFlush(x.handle)
                start=time.monotonic(); ack=None; visible=None; capture_times=[]; points=[]
                while time.monotonic()-start < .55:
                    query_start=time.monotonic();g=geometry(w);query_end=time.monotonic()
                    if ack is None and g[1]!=before[1]: ack=query_end-start
                    if mode=='capture':
                        a=time.monotonic();pix=Gdk.pixbuf_get_from_window(root,600,40,1,680);b=time.monotonic()
                        if pix is None:raise RuntimeError('No root image')
                        capture_times.append(b-a)
                        data=pix.get_pixels();stride=pix.get_rowstride()
                        rows=[i for i in range(680) if tuple(data[i*stride:i*stride+3])==(0x25,0xa9,0xdf)]
                        top=min(rows)+40 if rows else None
                        points.append(dict(capture_begin=a-start,capture_end=b-start,geometry=g,body_top=top))
                        if visible is None and top is not None and abs(top-before[1])>5:visible=b-start
                    time.sleep(.005)
                if ack is None:raise AssertionError('No WM acknowledgement')
                if mode=='capture' and visible is None:raise AssertionError('No visible motion')
                item=dict(backend=backend,mode=mode,cycle=cycle,ack_ms=round(ack*1000,3),first_visible_ms=round(visible*1000,3) if visible else None,
                          capture_mean_ms=round(statistics.mean(capture_times)*1000,3) if capture_times else None,
                          capture_max_ms=round(max(capture_times)*1000,3) if capture_times else None,points=points)
                records.append(item)
                print(json.dumps({k:v for k,v in item.items() if k!='points'}),flush=True)
        x.destroy(w)
    Path('/var/tmp/motion-timing-records.json').write_text(json.dumps(records))
    print(json.dumps(dict(summary=True,cases=len(records),scope='X11 acknowledgement and root capture, not physical presentation')),flush=True)
finally:
    x.close()
    for p,data in saved.items():
        if data is None:p.unlink(missing_ok=True)
        else:p.write_bytes(data)
    if backend_env is None:os.environ.pop('CARPATIC_ANIMATION_BACKEND',None)
    else:os.environ['CARPATIC_ANIMATION_BACKEND']=backend_env
    command('carpatic-animations','apply')
