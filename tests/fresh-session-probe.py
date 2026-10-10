#!/usr/bin/env python3
"""Installed-component acceptance probe; private guest Xvfb and real user bus only."""
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

assert os.environ.get('CARPATIC_VM_TEST') == '1'
assert not os.environ.get('WAYLAND_DISPLAY')
assert re.fullmatch(r':[1-9][0-9]+', os.environ.get('DISPLAY', ''))
def private_xvfb_exists():
    for p in Path('/proc').glob('[0-9]*'):
        try:
            if b'Xvfb\x00'+os.environ['DISPLAY'].encode()+b'\x00' in (p/'cmdline').read_bytes(): return True
        except OSError: pass
    return False
assert private_xvfb_exists()
assert os.getuid() != 0

def command(*args):
    return subprocess.check_output(args, text=True, timeout=5).strip()
def wait_for(fn, seconds=20):
    deadline = time.monotonic()+seconds
    while time.monotonic() < deadline:
        try:
            result=fn()
            if result: return result
        except subprocess.CalledProcessError: pass
        time.sleep(.05)
    raise AssertionError('Timed out awaiting installed component')

def desktop_window():
    ids=command('xdotool','search','--class','Xfdesktop').splitlines()
    return next((int(w) for w in ids if '_NET_WM_WINDOW_TYPE_DESKTOP' in command('xprop','-id',w,'_NET_WM_WINDOW_TYPE')), None)

desktop=wait_for(desktop_window)
clients=command('xprop','-root','_NET_CLIENT_LIST')
assert hex(desktop) in clients, (desktop,clients)
# Welcome/profile dialogs can legitimately cover the target on a repeat login.
# Minimize this account's ordinary fixture windows before testing desktop input.
def focus_exposed_desktop():
    listed=command('xprop','-root','_NET_CLIENT_LIST')
    for wid in re.findall(r'0x[0-9a-fA-F]+', listed):
        if int(wid,16)==desktop: continue
        kind=command('xprop','-id',wid,'_NET_WM_WINDOW_TYPE')
        if any(t in kind for t in ('DESKTOP','DOCK','NOTIFICATION','TOOLTIP','MENU')): continue
        command('xdotool','windowminimize',wid)
    command('xdotool','mousemove','--sync','1100','600','click','1')
    return int(command('xdotool','getwindowfocus'))==desktop
wait_for(focus_exposed_desktop)
desktop_focus=desktop
wallpaper=command('xfconf-query','-c','xfce4-desktop','-lv')
assert 'last-image' in wallpaper and '/carpatic/' in wallpaper, wallpaper
assert (Path.home()/'Desktop').is_dir()
notifiers=[]
for proc in Path('/proc').glob('[0-9]*'):
    try:
        if proc.stat().st_uid != os.getuid(): continue
        argv=proc.joinpath('cmdline').read_bytes().split(b'\0')
        if b'notify-service' in argv and any(b'carpatic-reminders' in arg for arg in argv):
            notifiers.append(int(proc.name))
    except OSError: pass
assert len(notifiers)==1, notifiers

import gi
gi.require_version('Gtk','3.0')
from gi.repository import GLib,Gio
sys.path[:0]=['/usr/local/lib/carpatic-reminders','/usr/local/lib/carpatic-panel']
from carpatic_reminders.app import RemindersApplication
from carpatic_reminders.store import Store
from carpatic_panel.flyout_cal import CalModel,CalView
from carpatic_panel.theme import Theme,DEFAULT_LIGHT
app=RemindersApplication()
assert app.register(None) and not app.get_is_remote()
cal=CalModel(today=dt.date(2030,2,17),data=str(Path.home()/'calendar-fixture'))
closed=[]
view=CalView(Theme(DEFAULT_LIGHT),cal,None,on_close=lambda: closed.append(True))
nodes={node.id:node for node in view.build() if node.id}
# Invoke the actual calendar Add action; its subprocess routes over the real bus
# to the registered installed application, with no Popen or app mocks.
nodes['cal:new-reminder'].on_click(nodes['cal:new-reminder'])
context=GLib.MainContext.default()
def pump_until(fn, seconds=10):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        while context.pending(): context.iteration(False)
        if fn(): return
        time.sleep(.01)
    raise AssertionError('Calendar/application action did not complete')
pump_until(lambda: app.window is not None and not app.window.busy and app.window.date.get_text()=='2030-02-17')
assert app.window.day=='2030-02-17', app.window.day
assert closed
app.window.title.set_text('Fresh-session calendar reminder')
app.window.save_button.clicked()
pump_until(lambda: not app.window.busy)
records=Store().list()
record=records[-1]
expected_pending=sum(not item['completed'] and item['due_date']=='2030-02-17' for item in records)
assert record['title']=='Fresh-session calendar reminder' and record['due_date']=='2030-02-17'
view._load_reminders()
pump_until(lambda: view.reminders_day==cal.selected and view.reminders_count==expected_pending)
app.window.destroy()
if view._reminders_timer:
    if context.find_source_by_id(view._reminders_timer): GLib.source_remove(view._reminders_timer)
print(json.dumps({'uid':os.getuid(),'desktop':hex(desktop),'desktop_focus_before_app':hex(desktop_focus),'notifier_count':len(notifiers),'wallpaper_settings':wallpaper,'calendar_date':record['due_date'],'calendar_pending':view.reminders_count,'real_bus_activation':True},indent=2))
