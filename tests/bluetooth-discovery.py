#!/usr/bin/env python3
"""Modern BlueZ command fixtures; optional guarded private GTK discovery UI."""
import ast, os, re, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
GTK_MODE='--gtk' in sys.argv
if GTK_MODE:
 sys.argv.remove('--gtk')
 tree=ast.parse((ROOT/'tests/notes-gui.py').read_text());exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='guard'],type_ignores=[]),'existing private GTK guard','exec'));guard()
 sys.path.insert(0,str(ROOT/'integration/carpatic/settings/lib'))
 from cset import ui,sysutil
 from gi.repository import Gtk,GLib

class Button:
 def __init__(self):self.label='Scan'
 def set_label(self,value):self.label=value
 def connect(self,*args):pass
class Widget:
 def __init__(self,title='',sub='',*args,**kwargs):self.title=title;self.sub=sub;self.key=kwargs.get('key');self.busy=False;self.sensitive=True;self.buttons=[Button()];self.rows=[];self.list=SimpleNamespace(remove=lambda row:None)
 def set_value_quiet(self,v):self.value=v
 def set_visible(self,v):self.visible=v
 def set_no_show_all(self,v):pass
 def set_title(self,v):self.title=v
 def set_sub(self,v):self.sub=v
 def set_busy(self,v):self.busy=v
 def set_sensitive(self,v):self.sensitive=v
 def add(self,row):self.rows.append(row)
 def show_all(self):pass

def subject(su,row=Widget):
 ns={'Page':object,'su':su,'re':re,'os':os,'ButtonRow':row}
 source=Path(os.environ.get('CARPATIC_BLUETOOTH_TEST_SOURCE',ROOT/'integration/carpatic/settings/lib/cset/pages/network.py'))
 tree=ast.parse(source.read_text());exec(compile(ast.Module(body=[n for n in tree.body if getattr(n,'name',None)=='BluetoothPage'],type_ignores=[]),'actual BluetoothPage','exec'),ns)
 return ns['BluetoothPage']()

class Commands(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='carpatic-bluez-discovery-');self.addCleanup(self.temp.cleanup)
  self.log=Path(self.temp.name)/'commands';self.pidfile=Path(self.temp.name)/'pid'
  executable=Path(self.temp.name)/'bluetoothctl';executable.write_text('''#!/bin/sh
printf '%s\n' "$*" >> "$BT_COMMAND_LOG"
case "$1" in
 --timeout)
  case "$BT_SCAN_MODE" in
   scan_failure) echo 'Failed to start discovery'; exit 1;;
   scan_no_ack) echo 'No default controller available'; exit 0;;
   timeout) echo $$ > "$BT_PID_FILE"; exec /bin/sleep 1;;
   *) echo 'Discovery started'; exit 0;;
  esac;;
 paired-devices) echo 'Unsupported legacy command' >&2; exit 1;;
 devices)
  if [ "$2" = Paired ]; then
   case "$BT_SCAN_MODE" in paired_failure) exit 1;; paired_malformed) echo 'Malformed';; empty) :;; *) echo 'Device 02:00:00:00:00:0a Fixture Paired';; esac
  else
   case "$BT_SCAN_MODE" in
    devices_failure) exit 1;; devices_malformed) echo 'Device not-a-MAC Fixture Invalid';;
    empty) :;;
    *) printf 'Device 02:00:00:00:00:0A Fixture Paired\nDevice 02:00:00:00:00:0b Fixture New\n';;
   esac
  fi;;
 *) echo 'Unexpected action attempted' >&2; exit 2;;
esac
''');executable.chmod(0o700)
  self.env=patch.dict(os.environ,{'PATH':self.temp.name+os.pathsep+os.environ['PATH'],'BT_SCAN_MODE':'success','BT_COMMAND_LOG':str(self.log),'BT_PID_FILE':str(self.pidfile)});self.env.start();self.addCleanup(self.env.stop)
  self.pending=[];self.page=subject(SimpleNamespace(bg=lambda work,done:self.pending.append((work,done))));self.page.find=Widget();self.page.find_row=Widget();self.page.nearby=[]
 def finish(self):
  work,done=self.pending.pop(0)
  try:result=work()
  except Exception as error:result=error
  done(result);return result
 def populate(self):self.page.scan();self.finish();self.assertEqual(len(self.page.nearby),1);return self.page.nearby[0]
 def test_modern_query_excludes_paired_and_normalizes_valid_mac(self):
  row=self.populate();self.assertEqual(row.title,'Fixture New');self.assertEqual(row.key,'near-02:00:00:00:00:0B')
  self.assertEqual(self.log.read_text().splitlines(),['--timeout 8 scan on','devices Paired','devices'])
 def test_failures_and_malformed_payload_preserve_cache_with_retry(self):
  old=self.populate()
  for mode in ('scan_failure','scan_no_ack','paired_failure','paired_malformed','devices_failure','devices_malformed'):
   with self.subTest(mode=mode):
    os.environ['BT_SCAN_MODE']=mode;self.page.scan();self.finish();self.assertEqual(self.page.nearby,[old]);self.assertFalse(old.sensitive);self.assertFalse(self.page.find_row.busy);self.assertEqual(self.page.find_row.buttons[0].label,'Retry');self.assertNotIn('Nothing new found',self.page.find_row.sub)
 def test_successful_empty_result_is_distinct(self):
  self.populate();os.environ['BT_SCAN_MODE']='empty';self.page.scan();self.finish();self.assertEqual(self.page.nearby,[]);self.assertEqual(self.page.find_row.buttons[0].label,'Scan');self.assertIn('Nothing new found',self.page.find_row.sub)
 def test_timeout_kills_and_reaps_owned_scan_process(self):
  old=self.populate();os.environ['BT_SCAN_MODE']='timeout';self.page.scan();actual_run=subprocess.run
  def short(*args,**kwargs):kwargs['timeout']=.04;return actual_run(*args,**kwargs)
  with patch('subprocess.run',side_effect=short):result=self.finish()
  self.assertIsInstance(result,subprocess.TimeoutExpired);self.assertEqual(self.page.nearby,[old]);self.assertEqual(self.page.find_row.title,'Bluetooth discovery timed out')
  pid=int(self.pidfile.read_text());self.assertFalse(Path('/proc',str(pid)).exists(),'owned scan process not reaped')
 def test_total_budget_shared_by_scan_and_both_list_queries(self):
  old=self.populate();self.page.scan();actual_run=subprocess.run;clock=[0.0];timeouts=[]
  def charged(*args,**kwargs):timeouts.append(kwargs['timeout']);result=actual_run(*args,**kwargs);clock[0]+=11;return result
  with patch('time.monotonic',side_effect=lambda:clock[0]),patch('subprocess.run',side_effect=charged):result=self.finish()
  self.assertIsInstance(result,subprocess.TimeoutExpired);self.assertEqual(self.page.nearby,[old])
  self.assertEqual(timeouts,[15,15,8]);self.assertFalse(self.page._scan_running)
 def test_prior_scan_cannot_enable_pair_after_refresh_off_or_error(self):
  for result in ({'powered':False,'devs':[]},{'error':'controller'}):
   with self.subTest(result=result):
    self.page.sw=Widget();self.page.refresh_row=Widget();self.page.dev=Widget();self.page.empty=Widget();self.page.rows=[]
    self.page.fill({'powered':True,'devs':[]})
    self.page.scan();self.page.fill(result);self.assertFalse(self.page.find.sensitive)
    self.finish()
    self.assertFalse(self.page.find.sensitive,'stale scan re-enabled discovery/Pair after off or unavailable refresh')
    self.assertTrue(all(not row.sensitive for row in self.page.nearby))
    self.assertEqual(self.page.refresh_row.buttons[0].label,'Retry' if 'error' in result else 'Refresh')
 def test_overlapping_scans_coalesce_one_followup(self):
  self.page.scan();self.page.scan();self.page.scan();self.assertEqual(len(self.pending),1);self.finish();self.assertEqual(len(self.pending),1);self.finish();self.assertFalse(self.page._scan_running);self.assertFalse(self.page._scan_again)

class PairingLaunch(unittest.TestCase):
 setUp=Commands.setUp
 finish=Commands.finish
 def launch(self,available,spawn=None):
  self.messages=[];self.page.win=SimpleNamespace(busy=lambda _:None,idle=self.messages.append)
  self.page.open_pairing.__globals__['su'].which=lambda _:available
  with patch.object(subprocess,'Popen',side_effect=spawn) as process:
   self.page.open_pairing('Fixture New');self.finish()
  return process
 def test_missing_manager_stays_gui_with_actionable_failure(self):
  process=self.launch(False);process.assert_not_called()
  self.assertIn('unavailable',self.messages[-1].lower())
 def test_spawn_failure_hides_raw_diagnostics(self):
  self.launch(True,OSError('private diagnostic'))
  self.assertIn('could not',self.messages[-1].lower());self.assertNotIn('private diagnostic',self.messages[-1])
 def test_running_manager_uses_plain_argv_without_pair_or_trust_commands(self):
  def pending(timeout):raise subprocess.TimeoutExpired('fixture',timeout)
  process=self.launch(True,lambda *args,**kwargs:SimpleNamespace(wait=pending))
  args,kwargs=process.call_args
  self.assertEqual(args[0],['blueman-manager'])
  self.assertEqual(kwargs['stdin'],subprocess.DEVNULL);self.assertEqual(kwargs['stdout'],subprocess.DEVNULL);self.assertEqual(kwargs['stderr'],subprocess.DEVNULL);self.assertTrue(kwargs['start_new_session'])
  self.assertFalse(self.log.exists(),'Settings ran a bluetoothctl pair/trust command')
  self.assertIn('Pair',self.messages[-1]);self.assertIn('Fixture New',self.messages[-1])
 def test_nonzero_manager_exit_is_failure(self):
  self.launch(True,lambda *args,**kwargs:SimpleNamespace(wait=lambda timeout:1))
  self.assertIn('could not',self.messages[-1].lower())

if GTK_MODE:
 class ActualGtk(unittest.TestCase):
  setUp=Commands.setUp
  def pump(self,predicate):
   deadline=time.monotonic()+3
   while time.monotonic()<deadline:
    while GLib.MainContext.default().pending():GLib.MainContext.default().iteration(False)
    if predicate():return
    time.sleep(.01)
   raise AssertionError('GTK discovery worker timed out')
  def test_visible_error_retains_disabled_row_and_retry_click_recovers(self):
   page=subject(SimpleNamespace(bg=sysutil.bg),ui.ButtonRow);page.find=ui.GroupCard('Nearby');page.find_row=ui.ButtonRow('Find new devices','','Scan',page.scan);page.find.add(page.find_row);page.nearby=[]
   win=Gtk.Window();win.add(page.find);win.show_all()
   try:
    page.scan();self.pump(lambda:not page._scan_running);old=page.nearby[0];self.assertEqual(old.title.get_text(),'Fixture New')
    os.environ['BT_SCAN_MODE']='scan_no_ack';page.scan();self.pump(lambda:not page._scan_running)
    self.assertEqual(page.nearby,[old]);self.assertFalse(old.is_sensitive());self.assertEqual(page.find_row.title.get_text(),'Could not start Bluetooth discovery');self.assertTrue(page.find_row.buttons[0].is_sensitive());self.assertEqual(page.find_row.buttons[0].get_label(),'Retry')
    os.environ['BT_SCAN_MODE']='success';page.find_row.buttons[0].emit('clicked');self.pump(lambda:not page._scan_running);self.assertTrue(page.nearby[0].is_sensitive());self.assertEqual(len(page.nearby),1)
   finally:win.destroy()
  def test_nearby_setup_button_routes_device_name_to_native_pairing(self):
   page=subject(SimpleNamespace(bg=sysutil.bg),ui.ButtonRow);page.find=ui.GroupCard('Nearby');page.find_row=ui.ButtonRow('Find new devices','','Scan',page.scan);page.find.add(page.find_row);page.nearby=[]
   win=Gtk.Window();win.add(page.find);win.show_all()
   try:
    page.scan();self.pump(lambda:not page._scan_running)
    button=page.nearby[0].buttons[0]
    self.assertEqual(button.get_label(),'Set up')
    with patch.object(page,'open_pairing') as launch:button.emit('clicked')
    launch.assert_called_once_with('Fixture New')
    self.assertEqual(self.log.read_text().splitlines(),['--timeout 8 scan on','devices Paired','devices'])
   finally:win.destroy()
  def test_off_or_unavailable_refresh_invalidates_prior_successful_scan(self):
   for result in ({'powered':False,'devs':[]},{'error':'controller'}):
    with self.subTest(result=result):
     pending=[];page=subject(SimpleNamespace(bg=lambda work,done:pending.append((work,done))),ui.ButtonRow)
     page.sw=ui.SwitchRow('Bluetooth','',True);page.dev=ui.GroupCard('My devices');page.find=ui.GroupCard('Nearby');page.empty=ui.InfoRow('No devices paired yet');page.dev.add(page.empty);page.rows=[]
     page.refresh_row=ui.ButtonRow('Bluetooth status','','Retry',page.refresh);page.find_row=ui.ButtonRow('Find new devices','','Scan',page.scan);page.find.add(page.find_row);page.nearby=[]
     win=Gtk.Window();box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL);win.add(box)
     for widget in (page.sw,page.refresh_row,page.dev,page.find):box.pack_start(widget,False,False,0)
     win.show_all()
     try:
      page.fill({'powered':True,'devs':[]});page.scan();work,done=pending.pop();done(work());old=page.nearby[0]
      page.scan();page.fill(result);work,done=pending.pop();done(work())
      self.assertFalse(page.find.get_sensitive(),'stale scan enabled Pair group after a newer off/unavailable observation');self.assertEqual(page.nearby,[old]);self.assertFalse(old.is_sensitive());self.assertTrue(page.refresh_row.buttons[0].is_sensitive())
      self.assertFalse(page._scan_running)
     finally:win.destroy()
if __name__=='__main__':unittest.main()
