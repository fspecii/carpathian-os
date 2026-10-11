#!/usr/bin/env python3
"""Real command exit statuses and optional private GTK join/cancel controls."""
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
 from cset import ui as actual_ui, sysutil
 from gi.repository import Gtk, GLib

def subject(su,ui):
 ns={'Page':object,'su':su,'ui':ui}
 tree=ast.parse((ROOT/'integration/carpatic/settings/lib/cset/pages/network.py').read_text())
 exec(compile(ast.Module(body=[n for n in tree.body if getattr(n,'name',None)=='WifiPage'],type_ignores=[]),'actual WifiPage','exec'),ns)
 return ns['WifiPage']()

class Commands(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='carpatic-wifi-connect-');self.addCleanup(self.temp.cleanup)
  self.calllog=Path(self.temp.name)/'called'
  executable=Path(self.temp.name)/'nmcli'
  executable.write_text('#!/bin/sh\nprintf "called\\n" >> "$FIXTURE_CALL_LOG"\nprintf "Untrusted command output: do not show this in the GUI.\\n" >&2\nexit "$FIXTURE_NMCLI_RC"\n');executable.chmod(0o700)
  self.env=patch.dict(os.environ,{'PATH':self.temp.name,'FIXTURE_NMCLI_RC':'8','FIXTURE_CALL_LOG':str(self.calllog)});self.env.start();self.addCleanup(self.env.stop)
  ns={'subprocess':subprocess,'DRY':False}
  tree=ast.parse((ROOT/'integration/carpatic/settings/lib/cset/sysutil.py').read_text());exec(compile(ast.Module(body=[n for n in tree.body if getattr(n,'name',None)=='run_sync'],type_ignores=[]),'actual run_sync','exec'),ns)
  self.run=ns['run_sync'];self.messages=[];self.scans=[];self.pending=[]
  self.page=subject(SimpleNamespace(run_sync=self.run,bg=lambda work,done:self.pending.append((work,done))),SimpleNamespace(ask_text=lambda *_:None))
  self.page.win=SimpleNamespace(busy=lambda _:None,idle=self.messages.append);self.page.scan=lambda:self.scans.append(True)
 def test_checked_exit_code_messages_and_no_raw_output(self):
  expected={0:'Connected.',8:'Wi-Fi service is unavailable.',3:'Joining the network timed out.',10:'That network is no longer available.',124:'Joining the network timed out.'}
  for rc,prefix in expected.items():
   with self.subTest(rc=rc):
    os.environ['FIXTURE_NMCLI_RC']=str(rc)
    self.page.connect({'ssid':'Fixture network','secure':False},False)
    work,done=self.pending.pop();res=work();self.assertEqual(res[0],rc);done(res)
    self.assertTrue(self.messages[-1].startswith(prefix),self.messages[-1]);self.assertNotIn('Untrusted command output',self.messages[-1])
  self.assertEqual(len(self.scans),5);self.assertEqual(len(self.calllog.read_text().splitlines()),5)
 def test_unknown_error_never_exposes_output_or_blames_password(self):
  os.environ['FIXTURE_NMCLI_RC']='1';self.page.connect({'ssid':'Fixture network','secure':False},False)
  work,done=self.pending.pop();done(work());self.assertEqual(self.messages[-1],'Could not join that network. Try again.')
 def test_cancel_does_not_queue_command_or_rescan(self):
  self.page.connect({'ssid':'Fixture secured network','secure':True},False)
  self.assertEqual(self.pending,[]);self.assertEqual(self.scans,[]);self.assertFalse(self.calllog.exists())
 def test_worker_exception_is_generic_failure(self):
  self.page.connect({'ssid':'Fixture network','secure':False},False)
  _,done=self.pending.pop();done(RuntimeError('Untrusted command output'))
  self.assertEqual(self.messages[-1],'Could not join that network. Try again.')

class ProfileActions(unittest.TestCase):
 setUp=Commands.setUp
 PROFILE={'name':'Renamed profile','ssid':'Fixture network','uuid':'11111111-1111-4111-8111-111111111111'}
 def test_duplicate_profiles_require_explicit_selection_without_join(self):
  network={'ssid':'Fixture network','secure':True,'active':False}
  other=dict(self.PROFILE,uuid='22222222-2222-4222-8222-222222222222')
  with patch.object(self.page,'connect') as connect:
   self.page.join_network(network,[self.PROFILE,other])
  connect.assert_not_called()
  self.assertIn('Known networks',self.messages[-1])
  self.assertEqual(self.pending,[])
 def test_one_profile_routes_exact_selected_identity(self):
  network={'ssid':'Fixture network','secure':True,'active':False}
  with patch.object(self.page,'connect') as connect:
   self.page.join_network(network,[self.PROFILE])
  connect.assert_called_once_with(network,True,self.PROFILE)
 def test_saved_connect_uses_exact_uuid_without_secret_prompt(self):
  calls=[]
  self.page.connect.__globals__['su'].run_sync=lambda *args,**kwargs:(calls.append((args,kwargs)) or (0,''))
  with patch.object(self.page.connect.__globals__['ui'],'ask_text') as prompt:
   self.page.connect({'ssid':'Fixture network','secure':True},True,self.PROFILE)
   work,done=self.pending.pop();done(work())
  prompt.assert_not_called()
  self.assertEqual(calls[0][0],('nmcli','con','up','uuid',self.PROFILE['uuid']))
  self.assertEqual(self.messages[-1],'Connected.')
 def test_saved_failure_guides_configuration_without_raw_output(self):
  os.environ['FIXTURE_NMCLI_RC']='4'
  self.page.connect({'ssid':'Fixture network','secure':True},True,self.PROFILE)
  work,done=self.pending.pop();done(work())
  self.assertIn('Configure',self.messages[-1])
  self.assertNotIn('Untrusted command output',self.messages[-1])
 def configure_result(self, executable, spawn=None):
  self.page.configure.__globals__['su'].which=lambda _:bool(executable)
  with patch.object(subprocess,'Popen',side_effect=spawn) as process:
   self.page.configure(self.PROFILE)
   work,done=self.pending.pop();done(work())
  return process
 def test_missing_editor_returns_actionable_message_without_spawn(self):
  process=self.configure_result(None)
  process.assert_not_called()
  self.assertIn('unavailable',self.messages[-1].lower())
  self.assertIn('forget',self.messages[-1].lower())
  self.assertIn('join',self.messages[-1].lower())
 def test_editor_spawn_failure_returns_known_message(self):
  self.configure_result('/fixture/nm-connection-editor',OSError('private startup diagnostic'))
  self.assertIn('could not',self.messages[-1].lower())
  self.assertNotIn('private startup diagnostic',self.messages[-1])
 def test_running_editor_is_success_and_launches_exact_uuid(self):
  child=SimpleNamespace(wait=lambda timeout:(_ for _ in ()).throw(subprocess.TimeoutExpired('fixture',timeout)))
  process=self.configure_result('/fixture/nm-connection-editor',lambda *args,**kwargs:child)
  args,kwargs=process.call_args
  self.assertEqual(args[0],['nm-connection-editor','--edit='+self.PROFILE['uuid']])
  self.assertEqual(kwargs['stdin'],subprocess.DEVNULL)
  self.assertEqual(kwargs['stdout'],subprocess.DEVNULL)
  self.assertEqual(kwargs['stderr'],subprocess.DEVNULL)
  self.assertTrue(kwargs['start_new_session'])
  self.assertNotIn('could not',self.messages[-1].lower())
 def test_editor_immediate_nonzero_exit_is_failure(self):
  self.configure_result('/fixture/nm-connection-editor',lambda *args,**kwargs:SimpleNamespace(wait=lambda timeout:1))
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
   raise AssertionError('GTK worker/dialog timed out')
  def window(self):
   win=Gtk.Window();status=Gtk.Label();box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL);box.pack_start(status,False,False,0);win.add(box)
   win.busy=lambda message:status.set_text(message);win.idle=lambda message:status.set_text(message)
   page=subject(SimpleNamespace(run_sync=self.run,bg=sysutil.bg),actual_ui);page.win=win;scans=[];page.scan=lambda:scans.append(True)
   return win,box,status,page,scans
  def test_visible_failure_then_actual_retry_click(self):
   win,box,status,page,scans=self.window();button=Gtk.Button(label='Join again');box.pack_start(button,False,False,0)
   button.connect('clicked',lambda *_:page.connect({'ssid':'Fixture network','secure':False},False));win.show_all()
   try:
    button.emit('clicked');self.pump(lambda:len(scans)==1)
    self.assertEqual(status.get_text(),'Wi-Fi service is unavailable. Try again shortly.')
    os.environ['FIXTURE_NMCLI_RC']='0';button.emit('clicked');self.pump(lambda:len(scans)==2)
    self.assertEqual(status.get_text(),'Connected.');self.assertEqual(len(self.calllog.read_text().splitlines()),2)
   finally:win.destroy()
  def test_actual_password_dialog_cancel_never_invokes_nmcli(self):
   win,box,status,page,scans=self.window();win.show_all();cancelled=[]
   def cancel():
    dialogs=[w for w in Gtk.Window.list_toplevels() if isinstance(w,Gtk.Dialog) and w.get_visible()]
    if not dialogs:return True
    self.assertEqual(len(dialogs),1);dialogs[0].response(Gtk.ResponseType.CANCEL);cancelled.append(True);return False
   timer=GLib.timeout_add(20,cancel)
   try:
    page.connect({'ssid':'Fixture secured network','secure':True},False)
    self.assertEqual(cancelled,[True]);self.assertEqual(scans,[]);self.assertFalse(self.calllog.exists());self.assertEqual(status.get_text(),'')
   finally:
    if not cancelled:GLib.source_remove(timer)
    win.destroy()
if __name__=='__main__':unittest.main()
