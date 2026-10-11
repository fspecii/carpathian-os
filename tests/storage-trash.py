#!/usr/bin/env python3
"""Temporary GFile roots + injected virtual backend; never access real Trash.

Optional --gtk needs an owned private Xvfb and private dbus-run-session.
No host trash:/// enumeration or deletion, even under a private HOME.
"""
import ast
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'integration/carpatic/settings/lib/cset/pages/system.py'
MODULE=ROOT/'integration/carpatic/settings/lib/cset/trash.py'
spec=importlib.util.spec_from_file_location('tested_trash',MODULE)
trash=importlib.util.module_from_spec(spec);sys.modules[spec.name]=trash;spec.loader.exec_module(trash)
Gio=trash.Gio


def handlers():
    tree=ast.parse(SOURCE.read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='StoragePage')
    wanted={'on_show','_trash_start','_trash_done','refresh_trash','empty_trash'}
    body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in wanted]
    ns={'trash_backend':trash}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name='Page',bases=[],keywords=[],body=body,decorator_list=[])],type_ignores=[])),str(SOURCE),'exec'),ns)
    return ns,ns['Page']


class Backend(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name);self.root=Gio.File.new_for_path(str(self.path))
    def test_hidden_unicode_spaces_and_symlink_target_preserved(self):
        target=self.path/'outside';target.mkdir();(target/'valuable').write_text('keep')
        items=self.path/'items';items.mkdir()
        for name in ('.hidden','two words','șț日本'): (items/name).write_text('trash')
        (items/'.link').symlink_to(target,target_is_directory=True)
        root=Gio.File.new_for_path(str(items))
        self.assertEqual(trash.inspect_trash(root=root).count,4)
        result=trash.empty_trash(root=root)
        self.assertEqual(result,trash.TrashResult(count=0))
        self.assertEqual((target/'valuable').read_text(),'keep');self.assertTrue(items.is_dir())
    def test_nonempty_local_directory_failure_is_not_empty(self):
        (self.path/'folder').mkdir();(self.path/'folder/file').write_text('stay')
        result=trash.empty_trash(root=self.root)
        self.assertEqual(result.count,1);self.assertEqual(result.failed,1)
        self.assertIn('could not be deleted',trash.status_text(result))
    def test_backend_unavailable_is_honest_and_does_not_delete(self):
        unavailable=SimpleNamespace(enumerate_children=lambda *a: (_ for _ in ()).throw(OSError('unavailable')))
        self.assertTrue(trash.inspect_trash(root=unavailable).unavailable)
        self.assertTrue(trash.empty_trash(root=unavailable).unavailable)
        self.assertIn('Refresh',trash.status_text(trash.TrashResult(unavailable=True)))
    def test_virtual_top_level_delete_and_fresh_scan_not_recursion(self):
        # Simulate GVFS handling whole folder + metadata. No physical media claim.
        entries={'.folder':object(),'file ș':object()};calls=[]
        class Item:
            def __init__(self,name): self.name=name
            def delete(self,cancel): calls.append(self.name);entries.pop(self.name);return True
        class Enum:
            def __init__(self): self.names=iter(list(entries))
            def next_file(self,cancel): return next(self.names,None)
            def get_child(self,name): return Item(name)
            def close(self,cancel): return True
        class Virtual:
            def enumerate_children(self,attrs,flags,cancel):
                self_outer.assertEqual(flags,Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS)
                return Enum()
        self_outer=self;result=trash.empty_trash(root=Virtual())
        self.assertEqual(result.count,0);self.assertEqual(calls,['.folder','file ș'])
    def test_final_scan_failure_does_not_claim_empty(self):
        calls=iter([iter([]),OSError('backend lost')])
        def children(*args):
            result=next(calls)
            if isinstance(result,Exception): raise result
            return result
        with patch.object(trash,'_children',side_effect=children): result=trash.empty_trash(root=object())
        self.assertTrue(result.unavailable);self.assertNotEqual(trash.status_text(result),'The Trash is empty')
    def test_new_arrival_is_preserved_and_reported_after_deletion(self):
        class Item:
            def delete(self,cancel): return True
        calls=iter([iter([Item()]),iter([Item()])])
        with patch.object(trash,'_children',side_effect=lambda *a:next(calls)):
            self.assertEqual(trash.empty_trash(root=object()).count,1)
    def test_default_root_is_only_standard_virtual_uri(self):
        with patch.object(Gio.File,'new_for_uri',return_value=self.root) as factory:
            result=trash.inspect_trash()
        factory.assert_called_once_with('trash:///');self.assertEqual(result.count,0)


class Handlers(unittest.TestCase):
    def setUp(self):
        self.ns,Page=handlers();self.page=Page();self.page._trash_busy=False
        class Button:
            def set_sensitive(self,value): self.sensitive=value
        class Row:
            buttons=[Button(),Button()]
            def set_sub(self,value): self.sub=value
            def set_busy(self,value): self.busy=value
        self.page.trash_row=Row();self.queued=[]
        self.ns['su']=SimpleNamespace(bg=lambda work,done:self.queued.append((work,done)))
        self.ns['ui']=SimpleNamespace(confirm=lambda *a:True);self.page.win=object()
    def test_error_keeps_refresh_available_and_never_empty(self):
        self.page._trash_done(RuntimeError('failed'))
        self.assertIn('unavailable',self.page.trash_row.sub)
        self.assertFalse(self.page.trash_row.buttons[0].sensitive)
        self.assertTrue(self.page.trash_row.buttons[1].sensitive)
    def test_delete_worker_busy_and_remaining_items_allow_retry(self):
        self.page.empty_trash();self.page.empty_trash()
        self.assertEqual(len(self.queued),1);self.assertIs(self.queued[0][0],trash.empty_trash)
        self.assertTrue(self.page._trash_busy)
        self.queued[0][1](trash.TrashResult(count=2,failed=1))
        self.assertTrue(self.page.trash_row.buttons[0].sensitive)
        self.assertIn('could not be deleted',self.page.trash_row.sub)
    def test_revisit_refreshes_without_gui_thread_scan(self):
        self.page.on_show();self.page.on_show()
        self.assertEqual(len(self.queued),1);self.assertIs(self.queued[0][0],trash.inspect_trash)
        self.queued[0][1](trash.TrashResult(count=0))
        self.assertEqual(self.page.trash_row.sub,'The Trash is empty')
        self.assertFalse(self.page.trash_row.buttons[0].sensitive)


if '--gtk' in sys.argv:
    sys.argv.remove('--gtk')
    import re
    guard_tree=ast.parse((ROOT/'tests/notes-gui.py').read_text())
    guard_node=next(n for n in guard_tree.body if isinstance(n,ast.FunctionDef) and n.name=='guard')
    exec(compile(ast.Module(body=[guard_node],type_ignores=[]),'private-display-guard','exec'),globals())
    guard()
    sys.path.insert(0,str(ROOT/'integration/carpatic/settings/lib'))
    from cset import ui
    from gi.repository import Gtk, GLib
    class ActualGTK(unittest.TestCase):
        def test_actual_worker_refresh_keeps_main_loop_responsive(self):
            import threading, time
            from cset import sysutil
            ns,Page=handlers();page=Page();page._trash_busy=False
            ns['su']=sysutil;ns['ui']=ui
            row=ui.ButtonRow('Empty the Trash','Checking','Empty',page.empty_trash)
            row.add_button('Refresh',page.refresh_trash);page.trash_row=row
            window=Gtk.Window();window.add(row);window.show_all();self.addCleanup(window.destroy)
            ready=threading.Event();release=threading.Event();worker_ids=[]
            original=trash.inspect_trash
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory);(path/'.hidden').write_text('controlled')
                def work():
                    worker_ids.append(threading.get_ident());ready.set()
                    if not release.wait(3): raise RuntimeError('test release timed out')
                    return original(root=Gio.File.new_for_path(directory))
                with patch.object(trash,'inspect_trash',side_effect=work):
                    page.refresh_trash();self.assertTrue(ready.wait(2))
                    ticks=[];GLib.idle_add(lambda:(ticks.append(True),False)[1])
                    context=GLib.MainContext.default()
                    while context.pending():context.iteration(False)
                    self.assertTrue(ticks);self.assertTrue(page._trash_busy)
                    self.assertNotEqual(worker_ids,[threading.get_ident()])
                    release.set();deadline=time.monotonic()+3
                    while page._trash_busy and time.monotonic()<deadline:
                        while context.pending():context.iteration(False)
                        time.sleep(.01)
                    self.assertFalse(page._trash_busy)
                    self.assertTrue(row.buttons[0].get_sensitive())
                    self.assertTrue((path/'.hidden').exists())

        def test_real_buttons_confirmation_cancel_and_verified_status(self):
            ns,Page=handlers();page=Page();page._trash_busy=False
            page.win=Gtk.Window();self.addCleanup(page.win.destroy)
            ns['ui']=ui;queued=[];ns['su']=SimpleNamespace(bg=lambda work,done:queued.append((work,done)))
            page.trash_row=ui.ButtonRow('Empty the Trash','2 items','Empty',page.empty_trash,'destructive')
            page.trash_row.add_button('Refresh',page.refresh_trash)
            page.win.add(page.trash_row);page.win.show_all()
            def respond(response):
                def answer():
                    dialogs=[w for w in Gtk.Window.list_toplevels() if isinstance(w,Gtk.MessageDialog)]
                    if not dialogs: return True
                    self.assertEqual(len(dialogs),1)
                    dialogs[0].response(response);return False
                GLib.timeout_add(10,answer)
            respond(Gtk.ResponseType.CANCEL);page.trash_row.buttons[0].clicked()
            self.assertEqual(queued,[])
            respond(Gtk.ResponseType.OK);page.trash_row.buttons[0].clicked()
            self.assertEqual(len(queued),1)
            self.assertFalse(page.trash_row.buttons[0].get_sensitive())
            queued.pop()[1](trash.TrashResult(count=1,failed=1))
            self.assertTrue(page.trash_row.buttons[0].get_sensitive())
            page.trash_row.buttons[1].clicked();self.assertEqual(len(queued),1)
            queued.pop()[1](trash.TrashResult(unavailable=True))
            self.assertFalse(page.trash_row.buttons[0].get_sensitive())
            self.assertTrue(page.trash_row.buttons[1].get_sensitive())
            page.trash_row.buttons[1].clicked();queued.pop()[1](trash.TrashResult(count=0))
            self.assertFalse(page.trash_row.buttons[0].get_sensitive())

if __name__=='__main__': unittest.main(verbosity=2)
