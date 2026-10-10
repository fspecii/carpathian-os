#!/usr/bin/env python3
"""Real RGB GTK menu surface must expose backdrop pixels at rounded corners."""
import json
import os
from pathlib import Path
import signal
import sys
import time

if (os.environ.get('CARPATIC_VM_TEST')!='1' or not Path('/etc/alpine-release').is_file()
        or os.environ.get('DISPLAY')!=':0' or 'WAYLAND_DISPLAY' in os.environ):
    raise SystemExit('Explicit isolated Alpine Xorg :0 only')
if os.system('pgrep -x i3lock >/dev/null')==0: raise SystemExit('Fixture locked')
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,Gdk
from rendering import Display,COLOR,command

negative='--negative-control' in sys.argv
cfg=Path.home()/'.config/carpatic'
paths=[cfg/'animations.json',cfg/'reduced-motion']
saved={p:p.read_bytes() if p.exists() else None for p in paths}
old_backend=os.environ.get('CARPATIC_ANIMATION_BACKEND')
x=Display();menu=None
results=[]
try:
    base=x.create('RGB menu corner backdrop',COLOR,500,500,override=True)
    x.x.XMapWindow(x.handle,base);x.sync()
    command('xdotool','windowmove',str(base),'100','100')
    for backend in ('glx','xrender'):
        os.environ['CARPATIC_ANIMATION_BACKEND']=backend
        state=json.loads(command('carpatic-animations','get','--json'))
        state.update(enabled=True,reduced=False,menus=True)
        paths[0].write_text(json.dumps(state));paths[1].unlink(missing_ok=True)
        command('carpatic-animations','apply')
        if negative:
            # Actual parser/rendering fault control, not a mocked paint result.
            config=cfg/'window-animations.conf'
            text=config.read_text();assert 'corner-radius = 8;' in text
            config.write_text('\n'.join(line for line in text.splitlines() if 'corner-radius = 8;' not in line)+'\n')
            pid=int((Path('/tmp/carpatic-runtime-0/window-animations/_0/pid')).read_text())
            os.kill(pid,signal.SIGUSR1);time.sleep(.7)
        menu=Gtk.Menu();popup=menu.get_toplevel()
        visual=menu.get_screen().get_system_visual()
        menu.set_visual(visual);popup.set_visual(visual)
        popup.get_style_context().add_class('corner-rgb-fixture')
        css=Gtk.CssProvider();css.load_from_data(b'window.corner-rgb-fixture {background-color:#203040;} menu {background-color:#203040;border-radius:8px;border:1px solid #506070;box-shadow:none;margin:0;padding:4px;} menuitem, menuitem:hover, menuitem:selected, menuitem:active {background-color:#203040;background-image:none;}')
        popup.get_style_context().add_provider(css,Gtk.STYLE_PROVIDER_PRIORITY_USER)
        menu.get_style_context().add_provider(css,Gtk.STYLE_PROVIDER_PRIORITY_USER)
        for label in ('Test action one','Test action two','Test action three'):
            item=Gtk.MenuItem(label=label)
            item.get_style_context().add_provider(css,Gtk.STYLE_PROVIDER_PRIORITY_USER)
            menu.append(item)
        menu.show_all()
        rect=Gdk.Rectangle();rect.x=150;rect.y=150;rect.width=rect.height=1
        menu.popup_at_rect(Gdk.get_default_root_window(),rect,Gdk.Gravity.NORTH_WEST,Gdk.Gravity.NORTH_WEST,None)
        end=time.monotonic()+.5
        while time.monotonic()<end:
            while Gtk.events_pending():Gtk.main_iteration_do(False)
            time.sleep(.005)
        g=dict(line.split('=',1) for line in command('xdotool','getwindowgeometry','--shell',str(popup.get_window().get_xid())).splitlines() if '=' in line)
        gx,gy,w,h=[int(g[key]) for key in ('X','Y','WIDTH','HEIGHT')]
        image=x.x.XGetImage(x.handle,x.root,gx,gy,w,h,0xFFFFFFFF,2)
        assert image,'No menu capture'
        try:
            corners=[x.x.XGetPixel(image,a,b)&0xFFFFFF for a,b in [(0,0),(w-1,0),(0,h-1),(w-1,h-1)]]
            interior=x.x.XGetPixel(image,8,20)&0xFFFFFF
        finally:x.x.XDestroyImage(image)
        assert interior==0x203040,dict(reason='Fixture body not rendered',interior=hex(interior))
        correct=all(p==COLOR for p in corners)
        item=dict(backend=backend,negative_control=negative,corners=[hex(p) for p in corners],interior=hex(interior),correct=correct)
        results.append(item);print(json.dumps(item),flush=True)
        assert (not correct) if negative else correct,item
        menu.popdown();menu.destroy();menu=None
    print(json.dumps(dict(summary=True,cases=len(results),negative_control=negative,passed=True)),flush=True)
finally:
    if menu:menu.popdown();menu.destroy()
    x.close()
    for p,data in saved.items():
        if data is None:p.unlink(missing_ok=True)
        else:p.write_bytes(data)
    if old_backend is None:os.environ.pop('CARPATIC_ANIMATION_BACKEND',None)
    else:os.environ['CARPATIC_ANIMATION_BACKEND']=old_backend
    command('carpatic-animations','apply')
