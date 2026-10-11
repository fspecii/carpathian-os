#!/usr/bin/env python3
"""Checked Bluetooth reads through owned command fixtures; optional private GTK."""
import ast, os, re, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
GTK_MODE='--gtk' in sys.argv
if GTK_MODE:
 sys.argv.remove('--gtk')
 tree=ast.parse((ROOT/'tests/notes-gui.py').read_text())
 exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='guard'],type_ignores=[]),'existing private GTK guard','exec'));guard()
 sys.path.insert(0,str(ROOT/'integration/carpatic/settings/lib'))
 from cset import ui, sysutil
 from gi.repository import Gtk, GLib

def subject(su,widgets=None):
 ns={'Page':object,'su':su,'os':os,'re':re,'ButtonRow':Widget}
 if widgets:ns.update(widgets)
 tree=ast.parse((ROOT/'integration/carpatic/settings/lib/cset/pages/network.py').read_text())
 exec(compile(ast.Module(body=[n for n in tree.body if getattr(n,'name',None) in ('BluetoothPage','parse_bt_info')],type_ignores=[]),'actual BluetoothPage','exec'),ns)
 return ns['BluetoothPage']()

class Button:
 def __init__(self):self.label='Retry'
 def set_label(self,value):self.label=value
 def connect(self,*args):pass
class Widget:
 def __init__(self,title='',sub='',*args,**kwargs):
  self.title=title;self.sub=sub;self.value=True;self.visible=False;self.sensitive=True;self.busy=False;self.rows=[];self.buttons=[Button()];self.list=SimpleNamespace(remove=lambda row:None)
 def set_value_quiet(self,value):self.value=value
 def set_sensitive(self,value):self.sensitive=value
 def set_sub(self,value):self.sub=value
 def set_title(self,value):self.title=value
 def set_visible(self,value):self.visible=value
 def set_no_show_all(self,value):pass
 def set_busy(self,value):self.busy=value
 def add(self,row):self.rows.append(row)
 def hide(self):self.visible=False
 def show_all(self):self.visible=True
 def add_button(self,*args):pass

class Commands(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='carpatic-bluez-refresh-');self.addCleanup(self.temp.cleanup)
  command=Path(self.temp.name)/'bluetoothctl';command.write_text('''#!/bin/sh
case "$BT_FIXTURE" in
 unavailable) echo 'No default controller available'; exit 1;;
 timeout) /bin/sleep 0.2; exit 1;;
esac
if [ "$BT_FIXTURE" = budget ]; then /bin/sleep 0.02; fi
case "$1" in
 show)
  case "$BT_FIXTURE" in malformed_show) echo 'Unexpected controller output';; off) echo 'Powered: no';; *) echo 'Powered: yes';; esac;;
 devices)
  case "$BT_FIXTURE" in devices_error) echo 'Untrusted fixture error' >&2; exit 1;; malformed_devices) echo 'Unexpected list output';; budget) printf 'Device 02:00:00:00:00:01 Fixture One\nDevice 02:00:00:00:00:02 Fixture Two\nDevice 02:00:00:00:00:03 Fixture Three\n';; *) echo 'Device 02:00:00:00:00:01 Fixture Headphones';; esac;;
 info)
  case "$BT_FIXTURE" in info_error) echo 'Untrusted fixture error' >&2; exit 1;; malformed_info) echo 'Name: Missing state';; *) printf 'Paired: yes\nConnected: no\nIcon: audio-headphones\n';; esac;;
 *) exit 2;;
esac
''');command.chmod(0o700)
  self.env=patch.dict(os.environ,{'PATH':self.temp.name,'BT_FIXTURE':'success'});self.env.start();self.addCleanup(self.env.stop)
  self.page=subject(SimpleNamespace(bg=lambda work,done:done(work())))
  self.page.sw=Widget();self.page.refresh_row=Widget();self.page.dev=Widget();self.page.find=Widget();self.page.empty=Widget();self.page.rows=[]
 def populated(self):
  self.page.refresh();self.assertEqual(len(self.page.rows),1);return self.page.rows[0]
 def test_controller_failure_retains_cached_rows_radio_and_retry(self):
  old=self.populated();os.environ['BT_FIXTURE']='unavailable';self.page.refresh()
  self.assertEqual(self.page.rows,[old]);self.assertTrue(self.page.sw.value);self.assertFalse(self.page.sw.sensitive);self.assertFalse(self.page.dev.sensitive);self.assertFalse(self.page.find.sensitive);self.assertEqual(self.page.refresh_row.buttons[0].label,'Retry');self.assertEqual(self.page.refresh_row.title,'Bluetooth adapter is unavailable');self.assertFalse(self.page.empty.visible)
 def test_real_powered_no_is_distinct(self):
  os.environ['BT_FIXTURE']='off';self.page.refresh();self.assertFalse(self.page.sw.value);self.assertTrue(self.page.sw.sensitive);self.assertEqual(self.page.refresh_row.title,'Bluetooth is off');self.assertEqual(len(self.page.rows),1)
 def test_devices_info_and_malformed_failures_retain_known_rows(self):
  old=self.populated()
  for mode,title in [('devices_error','Could not read Bluetooth devices'),('info_error','Could not read Bluetooth device details'),('malformed_devices','Could not read Bluetooth devices'),('malformed_info','Could not read Bluetooth device details'),('malformed_show','Bluetooth adapter is unavailable')]:
   with self.subTest(mode=mode):
    os.environ['BT_FIXTURE']=mode;self.page.refresh();self.assertEqual(self.page.rows,[old]);self.assertEqual(self.page.refresh_row.title,title);self.assertNotIn('Untrusted',self.page.refresh_row.sub)
 def test_retry_success_reenables_stale_actions(self):
  self.populated();os.environ['BT_FIXTURE']='unavailable';self.page.refresh();os.environ['BT_FIXTURE']='success';self.page.refresh()
  self.assertTrue(self.page.sw.sensitive);self.assertTrue(self.page.dev.sensitive);self.assertTrue(self.page.find.sensitive);self.assertEqual(self.page.refresh_row.buttons[0].label,'Refresh');self.assertEqual(len(self.page.rows),1)
 def test_actual_subprocess_timeout_keeps_cached_state(self):
  old=self.populated();os.environ['BT_FIXTURE']='timeout';actual_run=subprocess.run
  def shortened(*args,**kwargs):kwargs['timeout']=.03;return actual_run(*args,**kwargs)
  pending=[];self.page.__class__.__dict__['refresh'].__globals__['su']=SimpleNamespace(bg=lambda work,done:pending.append((work,done)))
  self.page.refresh();work,done=pending.pop()
  with patch('subprocess.run',side_effect=shortened):
   try:result=work()
   except subprocess.TimeoutExpired as error:result=error
  done(result);self.assertEqual(self.page.rows,[old]);self.assertTrue(self.page.sw.value);self.assertFalse(self.page.refresh_row.busy);self.assertEqual(self.page.refresh_row.buttons[0].label,'Retry')
 def test_total_budget_stops_many_successful_slow_queries(self):
  old=self.populated();os.environ['BT_FIXTURE']='budget';actual_run=subprocess.run
  clock=[100.0];timeouts=[];successful=[];pending=[]
  def slow_success(*args,**kwargs):
   timeouts.append(kwargs['timeout']);result=actual_run(*args,**kwargs)
   self.assertEqual(result.returncode,0);successful.append(args[0]);clock[0]+=11
   return result
  self.page.__class__.__dict__['refresh'].__globals__['su']=SimpleNamespace(bg=lambda work,done:pending.append((work,done)))
  self.page.refresh();work,done=pending.pop();started=time.monotonic()
  # Real fixture commands are successful and slow; the injected monotonic
  # clock charges eleven seconds per completed read without a thirty-second
  # unit-test wait. Remaining budget must shrink across all device queries.
  with patch('time.monotonic',side_effect=lambda:clock[0]),patch('subprocess.run',side_effect=slow_success):
   try:result=work()
   except subprocess.TimeoutExpired as error:result=error
  self.assertIsInstance(result,subprocess.TimeoutExpired);self.assertLess(time.monotonic()-started,2)
  self.assertEqual(len(successful),3);self.assertEqual(timeouts,[15,15,8])
  self.assertEqual(successful[-1],['bluetoothctl','info','02:00:00:00:00:01'])
  done(result);self.assertEqual(self.page.rows,[old]);self.assertFalse(self.page.refresh_row.busy);self.assertFalse(self.page._refresh_running);self.assertEqual(self.page.refresh_row.buttons[0].label,'Retry')
 def test_overlapping_refreshes_coalesce(self):
  pending=[];self.page.__class__.__dict__['refresh'].__globals__['su']=SimpleNamespace(bg=lambda work,done:pending.append((work,done)))
  self.page.refresh();self.page.refresh();self.page.refresh();self.assertEqual(len(pending),1)
  work,done=pending.pop(0);done(work());self.assertEqual(len(pending),1)
  work,done=pending.pop(0);done(work());self.assertFalse(self.page._refresh_running);self.assertFalse(self.page._refresh_again)

if GTK_MODE:
 class ActualGtk(unittest.TestCase):
  setUp=Commands.setUp
  def pump(self,predicate):
   deadline=time.monotonic()+3
   while time.monotonic()<deadline:
    while GLib.MainContext.default().pending():GLib.MainContext.default().iteration(False)
    if predicate():return
    time.sleep(.01)
   raise AssertionError('GTK refresh callback timed out')
  def test_actual_cached_error_retry_and_power_off(self):
   page=subject(SimpleNamespace(bg=sysutil.bg),{'ButtonRow':ui.ButtonRow})
   page.sw=ui.SwitchRow('Bluetooth','',True);page.dev=ui.GroupCard('My devices');page.find=ui.GroupCard('Nearby');page.empty=ui.InfoRow('No devices paired yet');page.dev.add(page.empty);page.rows=[]
   page.refresh_row=ui.ButtonRow('Bluetooth status','','Retry',page.refresh);win=Gtk.Window();box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL);win.add(box)
   for widget in (page.sw,page.refresh_row,page.dev,page.find):box.pack_start(widget,False,False,0)
   win.show_all()
   try:
    page.refresh();self.pump(lambda:not page._refresh_running);old=page.rows[0]
    os.environ['BT_FIXTURE']='unavailable';page.refresh();self.pump(lambda:not page._refresh_running)
    self.assertEqual(page.rows,[old]);self.assertTrue(page.sw.get_value());self.assertFalse(page.sw.get_sensitive());self.assertFalse(old.is_sensitive());self.assertFalse(page.find.get_sensitive());self.assertTrue(page.refresh_row.buttons[0].is_sensitive());self.assertEqual(page.refresh_row.title.get_text(),'Bluetooth adapter is unavailable');self.assertFalse(page.empty.get_visible())
    os.environ['BT_FIXTURE']='success';page.refresh_row.buttons[0].emit('clicked');self.pump(lambda:not page._refresh_running)
    self.assertTrue(page.sw.get_sensitive());self.assertTrue(page.rows[0].is_sensitive());self.assertTrue(page.find.get_sensitive())
    os.environ['BT_FIXTURE']='off';page.refresh();self.pump(lambda:not page._refresh_running)
    self.assertFalse(page.sw.get_value());self.assertTrue(page.sw.get_sensitive());self.assertEqual(page.refresh_row.title.get_text(),'Bluetooth is off');self.assertEqual(len(page.rows),1)
   finally:win.destroy()
  def test_build_queues_worker_without_foreground_show(self):
   pending=[]
   def forbid(*args,**kwargs):raise AssertionError('foreground Bluetooth query')
   page=subject(SimpleNamespace(bg=lambda work,done:pending.append((work,done)),out=forbid),{'ButtonRow':ui.ButtonRow,'SwitchRow':ui.SwitchRow,'InfoRow':ui.InfoRow})
   page.win=SimpleNamespace();builder=ui.PageBuilder('Bluetooth');page.build(builder)
   try:
    self.assertEqual(len(pending),1);self.assertFalse(page.sw.get_sensitive());self.assertEqual(page.sw.sub.get_text(),'Checking status...');self.assertFalse(page.empty.get_visible());self.assertFalse(page.find.get_sensitive());self.assertTrue(page.refresh_row.buttons[0].is_sensitive())
   finally:builder.destroy()
if __name__=='__main__':unittest.main()
