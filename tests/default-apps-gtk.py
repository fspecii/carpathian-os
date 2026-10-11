#!/usr/bin/env python3
"""Private GTK controls and real MIME persistence with a temporary file receiver."""
import ast, importlib.util, os, re, sys, time, unittest, subprocess, tempfile, shutil
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
# Reuse the existing strict private-runtime/Xvfb/private-bus guard, before GTK.
tree=ast.parse((ROOT/'tests/notes-gui.py').read_text())
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='guard'],type_ignores=[]),'notes-gui guard','exec'))
guard()
sys.path.insert(0,str(ROOT/'integration/carpatic/settings/lib'))
from cset import ui, sysutil
from gi.repository import Gtk, GLib
spec=importlib.util.spec_from_file_location('default_apps_logic',ROOT/'tests/default-apps.py');logic=importlib.util.module_from_spec(spec);spec.loader.exec_module(logic)

def pump(predicate):
 deadline=time.monotonic()+3
 while time.monotonic()<deadline:
  while GLib.MainContext.default().pending():GLib.MainContext.default().iteration(False)
  if predicate():return
  time.sleep(.01)
 raise AssertionError('GTK/background callback timed out')

class ActualWidgets(unittest.TestCase):
 def setUp(self):
  self.calls=[];self.default='';self.rows=[];self.filled=False
  backend=SimpleNamespace(which=lambda _:False,desktop_entries=lambda:[('viewer.desktop','Fixture Viewer','',['text/plain'],'/bin/true')],out=lambda *a:self.default,bg=sysutil.bg)
  ns=logic.load(logic.ROOT/'pages/system.py',{'CATEGORIES','candidates','AppsPage'},{'Page':object,'su':backend,'PopupRow':ui.PopupRow,'InfoRow':ui.InfoRow})
  self.page=ns['AppsPage']();self.page.win=SimpleNamespace(on_page_filled=lambda _:setattr(self,'filled',True),apply=self.apply)
  self.window=Gtk.Window();self.box=Gtk.ListBox();self.window.add(self.box)
  def add(row):self.rows.append(row);self.box.add(row)
  self.page.build(SimpleNamespace(group=lambda:SimpleNamespace(add=add)))
  pump(lambda:self.filled);self.window.show_all();pump(lambda:self.window.get_mapped())
  self.row=self.page.rows['text/plain']
 def tearDown(self):self.window.destroy()
 def apply(self,*args,**kwargs):self.calls.append((args,kwargs))
 def click_option(self,index):
  self.row.pb.set_active(True)
  pump(lambda:self.row.pb.pop.get_visible())
  self.row.pb.pop.get_child().get_children()[index].emit('clicked')
 def test_real_sentinel_and_missing_handler_rows(self):
  self.assertEqual(self.row.pb.lab.get_text(),'Not configured');self.assertEqual(self.row.get_value(),'')
  self.assertEqual(len(self.rows),9)
  self.assertTrue(any(isinstance(r,ui.InfoRow) for r in self.rows));self.assertEqual(self.calls,[])
 def test_click_save_and_failed_change_requery(self):
  self.click_option(1)
  self.assertEqual(self.calls[0][0],('xdg-mime','default','viewer.desktop','text/plain'))
  self.default='viewer.desktop';self.calls[0][1]['done'](0,'')
  pump(lambda:self.row.get_value()=='viewer.desktop')
  self.assertEqual(self.row.pb.lab.get_text(),'Fixture Viewer')
  # Empty sentinel does not silently remove a saved association.
  self.click_option(0);pump(lambda:self.row.get_value()=='viewer.desktop')
  self.assertEqual(len(self.calls),1)
  # Failed backend write returns to actual absence instead of chosen label.
  self.default='';self.calls[0][1]['done'](1,'fixture failure')
  pump(lambda:self.row.get_value()=='')
  self.assertEqual(self.row.pb.lab.get_text(),'Not configured')
class RealAssociation(unittest.TestCase):
 def test_real_runner_persistence_and_fixture_file_receiver(self):
  with tempfile.TemporaryDirectory(prefix='carpatic-default-real-') as directory:
   root=Path(directory);home=root/'home';data=root/'data';config=root/'config';system=root/'system'
   for folder in (home,data/'applications',config,system):folder.mkdir(parents=True,mode=0o700)
   receiver=root/'receiver';received=root/'received';file=root/'a file with spaces.txt';file.write_text('isolated plain text fixture\n')
   receiver.write_text('#!/bin/sh\nprintf "%s" "$1" > "'+str(received)+'"\n');receiver.chmod(0o700)
   desktop=data/'applications/carpatic-fixture.desktop'
   desktop.write_text('[Desktop Entry]\nType=Application\nName=Fixture Receiver\nExec='+str(receiver)+' %f\nMimeType=text/plain;\nTerminal=false\n')
   # Expose MIME classification data read-only, without system applications.
   (data/'mime').symlink_to('/usr/share/mime',target_is_directory=True)
   binaries=root/'bin';binaries.mkdir();fallback=root/'fallback-used'
   for command in ('xdg-mime','xdg-open','file','grep','egrep','fgrep','sed','cut','head','tail','awk','basename','dirname','readlink','which','cat','tr','mkdir','touch','cp','mv','chmod'):
    executable=shutil.which(command)
    if executable:(binaries/command).symlink_to(executable)
   deny=binaries/'deny-fallback';deny.write_text('#!/bin/sh\nprintf "%s\n" "$0" >> "'+str(fallback)+'"\nexit 1\n');deny.chmod(0o700)
   for command in ('run-mailcap','mimeopen','x-www-browser','firefox'):(binaries/command).symlink_to(deny)
   env={'PATH':str(binaries),'BROWSER':str(deny),'HOME':str(home),'XDG_DATA_HOME':str(data),'XDG_CONFIG_HOME':str(config),'XDG_DATA_DIRS':str(system),'XDG_CONFIG_DIRS':str(system),'DE':'generic','XDG_CURRENT_DESKTOP':'','CSET_DRY':''}
   with patch.dict(os.environ,env),patch.object(sysutil,'DRY',False):
    subprocess.run([shutil.which('update-desktop-database',path='/usr/bin:/bin'),str(data/'applications')],check=True,capture_output=True,timeout=5)
    # Actual SettingsWindow serial command queue and su.spawn/run_sync; toolbar
    # and unrelated theme watcher replaced, no shell/backend command stubs.
    tree=ast.parse((logic.ROOT/'app.py').read_text());window=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='SettingsWindow')
    methods=[n for n in window.body if isinstance(n,ast.FunctionDef) and n.name in ('apply','_pump')]
    cls=ast.ClassDef(name='CommandWindow',bases=[],keywords=[],body=methods,decorator_list=[])
    ns={'os':os,'su':sysutil,'GLib':GLib};exec(compile(ast.fix_missing_locations(ast.Module(body=[cls],type_ignores=[])),'actual Settings command queue','exec'),ns)
    win=ns['CommandWindow']();win.BAR_COMMANDS=();win.busy=lambda *_:None;win.idle=lambda *_:None;win.watch_theme=lambda:None
    rows=[];filled=[];win.on_page_filled=lambda _:filled.append(True)
    page_ns=logic.load(logic.ROOT/'pages/system.py',{'CATEGORIES','candidates','AppsPage'},{'Page':object,'su':sysutil,'PopupRow':ui.PopupRow,'InfoRow':ui.InfoRow,'ButtonRow':ui.ButtonRow})
    page=page_ns['AppsPage']();page.win=win;page.build(SimpleNamespace(group=lambda:SimpleNamespace(add=rows.append)))
    pump(lambda:bool(filled));row=page.rows['text/plain']
    page.set_default('carpatic-fixture.desktop',('text/plain',))
    pump(lambda:not win.__dict__.get('_running') and row.get_value()=='carpatic-fixture.desktop')
    query=subprocess.run(['xdg-mime','query','default','text/plain'],check=True,capture_output=True,text=True,timeout=5)
    self.assertEqual(query.stdout.strip(),'carpatic-fixture.desktop')
    self.assertIn('carpatic-fixture.desktop',(config/'mimeapps.list').read_text())
    mime=subprocess.check_output(['xdg-mime','query','filetype',str(file)],text=True,timeout=5).strip()
    self.assertEqual(mime,'text/plain')
    subprocess.run(['xdg-open',str(file)],check=True,capture_output=True,timeout=5)
    self.assertFalse(fallback.exists(),'xdg-open used a fallback instead of fixture association')
    pump(received.exists);self.assertEqual(received.read_text(),str(file))
    # A new process still reads the persisted association, rather than widget state.
    self.assertEqual(subprocess.check_output(['xdg-mime','query','default','text/plain'],text=True,timeout=5).strip(),'carpatic-fixture.desktop')
if __name__=='__main__':unittest.main()
