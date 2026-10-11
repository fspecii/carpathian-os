#!/usr/bin/env python3
"""Checked read-only Wi-Fi queries using temporary nmcli; optional real GTK."""
import ast, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
GTK_MODE='--gtk' in sys.argv
if GTK_MODE:
 sys.argv.remove('--gtk');import re
 tree=ast.parse((ROOT/'tests/notes-gui.py').read_text())
 exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='guard'],type_ignores=[]),'existing private GTK guard','exec'));guard()
 sys.path.insert(0,str(ROOT/'integration/carpatic/settings/lib'))
 from cset import ui, sysutil
 from gi.repository import Gtk, GLib

def subject(su,widgets=None):
 ns={'os':os,'Page':object,'su':su}
 if widgets:ns.update(widgets)
 tree=ast.parse((ROOT/'integration/carpatic/settings/lib/cset/pages/network.py').read_text())
 nodes=[n for n in tree.body if getattr(n,'name',None) in ('WifiPage','split_t','parse_wifi_list','signal_icon')]
 exec(compile(ast.Module(body=nodes,type_ignores=[]),'actual WifiPage','exec'),ns)
 return ns['WifiPage']()

class Widget:
 def __init__(self,value=None):self.value=value;self.visible=True;self.sensitive=True;self.busy=False;self.title='';self.sub='';self.buttons=[SimpleNamespace(show=lambda:setattr(self,'visible',True),hide=lambda:setattr(self,'visible',False))]
 def set_busy(self,v):self.busy=v
 def set_title(self,v):self.title=v
 def set_sub(self,v):self.sub=v
 def set_value_quiet(self,v):self.value=v
 def set_sensitive(self,v):self.sensitive=v
 def clear(self):pass
 def hide(self):pass
 def set_no_show_all(self,v):pass

class Commands(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='carpatic-wifi-scan-');self.addCleanup(self.temp.cleanup)
  executable=Path(self.temp.name)/'nmcli'
  executable.write_text('''#!/bin/sh
if [ "$FAKE_WIFI_MODE" = service ]; then echo 'Error: NetworkManager is not running.' >&2; exit 8; fi
if [ "$1 $2" = 'radio wifi' ]; then
 case "$FAKE_WIFI_MODE" in off) echo disabled;; malformed) echo unexpected;; *) echo enabled;; esac
elif [ "$FAKE_WIFI_MODE" = scan ] && [ "$4" = dev ]; then echo 'Error: No Wi-Fi device found.' >&2; exit 10
elif [ "$FAKE_WIFI_MODE" = profiles ] && [ "$4" = con ]; then exit 1
fi
''');executable.chmod(0o700)
  self.env=patch.dict(os.environ,{'PATH':self.temp.name,'FAKE_WIFI_MODE':'service'});self.env.start();self.addCleanup(self.env.stop)
  self.page=subject(SimpleNamespace(bg=lambda work,done:done(work())))
  self.page.scan_row=Widget();self.page.sw=Widget(True);self.page.nets=Widget();self.page.known=Widget();self.old=Widget();self.page.nets_rows=[self.old]
 def test_service_failure_keeps_radio_and_retry(self):
  self.page.scan();self.assertTrue(self.page.sw.value);self.assertEqual(self.page.scan_row.title,'Wi-Fi service is unavailable');self.assertTrue(self.page.scan_row.visible);self.assertFalse(self.old.sensitive);self.assertFalse(self.page.scan_row.busy);self.assertFalse(self.page.sw.sensitive);self.assertFalse(self.page.known.sensitive)
 def test_scan_failure_is_not_empty_results_or_radio_off(self):
  self.page.sw.value=False;os.environ['FAKE_WIFI_MODE']='scan';self.page.scan();self.assertEqual(self.page.scan_row.title,'Could not scan for networks');self.assertTrue(self.page.sw.value);self.assertTrue(self.page.sw.sensitive);self.assertTrue(self.page.scan_row.visible)
 def test_profiles_failure_does_not_claim_no_networks(self):
  os.environ['FAKE_WIFI_MODE']='profiles';self.page.scan();self.assertEqual(self.page.scan_row.title,'Could not read saved networks')
 def test_genuine_radio_off_distinct(self):
  self.page.nets_rows=[];os.environ['FAKE_WIFI_MODE']='off';self.page.scan();self.assertFalse(self.page.sw.value);self.assertEqual(self.page.scan_row.title,'Wi-Fi is off');self.assertFalse(self.page.scan_row.visible)
 def test_successful_retry_empty_scan_is_honest(self):
  self.page.scan();self.page.nets_rows=[];os.environ['FAKE_WIFI_MODE']='success';self.page.scan();self.assertTrue(self.page.sw.value);self.assertEqual(self.page.scan_row.title,'No networks found');self.assertTrue(self.page.scan_row.visible);self.assertTrue(self.page.nets.sensitive);self.assertTrue(self.page.sw.sensitive);self.assertTrue(self.page.known.sensitive)
 def test_malformed_radio_is_error(self):
  os.environ['FAKE_WIFI_MODE']='malformed';self.page.scan();self.assertEqual(self.page.scan_row.title,'Could not check Wi-Fi');self.assertTrue(self.page.sw.value)
 def test_worker_exception_clears_busy_and_retains_retry(self):
  self.page.fill(subprocess.TimeoutExpired(['nmcli'],25));self.assertFalse(self.page.scan_row.busy);self.assertTrue(self.page.scan_row.visible);self.assertTrue(self.page.sw.value)
 def test_overlapping_scans_coalesce_one_followup(self):
  pending=[];ns=SimpleNamespace(bg=lambda work,done:pending.append((work,done)))
  page=subject(ns);page.scan_row=Widget();page.sw=Widget(True);page.nets=Widget();page.known=Widget();page.nets_rows=[]
  page.scan();page.scan();page.scan();self.assertEqual(len(pending),1)
  work,done=pending.pop(0);done(work());self.assertEqual(len(pending),1)
  work,done=pending.pop(0);done(work());self.assertFalse(page._scan_running);self.assertFalse(page._scan_again)

if GTK_MODE:
 class ActualGtk(unittest.TestCase):
  setUp=Commands.setUp
  def test_real_retry_click_and_radio_preservation(self):
   # Actual widgets, real worker/GLib dispatch and only temporary commands.
   page=subject(SimpleNamespace(bg=sysutil.bg),{'Gtk':Gtk,'Row':ui.Row,'ButtonRow':ui.ButtonRow})
   page.sw=ui.SwitchRow('Wi-Fi','',True);page.scan_row=ui.ButtonRow('Looking for networks','','Scan again',page.scan)
   page.nets=ui.GroupCard('Networks');page.known=ui.GroupCard('Known networks');page.nets_rows=[]
   win=Gtk.Window();box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL);win.add(box)
   for widget in (page.sw,page.nets,page.known):box.pack_start(widget,False,False,0)
   page.nets.add(page.scan_row);win.show_all()
   def pump(predicate):
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
     while GLib.MainContext.default().pending():GLib.MainContext.default().iteration(False)
     if predicate():return
     time.sleep(.01)
    raise AssertionError('actual GTK worker timed out')
   try:
    page.scan();pump(lambda:not page._scan_running)
    self.assertTrue(page.sw.sw.get_active());self.assertFalse(page.sw.get_sensitive());self.assertFalse(page.known.get_sensitive());self.assertEqual(page.scan_row.title.get_text(),'Wi-Fi service is unavailable');self.assertTrue(page.scan_row.buttons[0].get_visible())
    os.environ['FAKE_WIFI_MODE']='success';page.scan_row.buttons[0].emit('clicked');pump(lambda:not page._scan_running)
    self.assertTrue(page.sw.sw.get_active());self.assertTrue(page.sw.get_sensitive());self.assertTrue(page.known.get_sensitive());self.assertEqual(page.scan_row.title.get_text(),'No networks found');self.assertTrue(page.scan_row.buttons[0].get_visible());self.assertTrue(page.nets.get_sensitive())
   finally:win.destroy()
  def test_build_has_no_foreground_radio_query(self):
   pending=[]
   def forbid(*args,**kwargs):raise AssertionError('build queried radio on GTK thread')
   page=subject(SimpleNamespace(bg=lambda work,done:pending.append((work,done)),out=forbid),{'Gtk':Gtk,'Row':ui.Row,'ButtonRow':ui.ButtonRow,'SwitchRow':ui.SwitchRow})
   page.win=SimpleNamespace()
   builder=ui.PageBuilder('Wi-Fi');page.build(builder)
   try:
    self.assertFalse(page.sw.get_sensitive());self.assertEqual(page.sw.sub.get_text(),'Checking status...');self.assertEqual(len(pending),1)
   finally:builder.destroy()
if __name__=='__main__':unittest.main()
