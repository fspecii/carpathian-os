#!/usr/bin/env python3
"""Real GTK rows/popover clicks; isolated backend, no application launching."""
import ast, importlib.util, os, re, sys, time, unittest
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
if __name__=='__main__':unittest.main()
