#!/usr/bin/env python3
"""Actual cache cleanup only in temporary roots; never clean the host cache."""
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
MODULE=ROOT/'integration/carpatic/settings/lib/cset/cache_cleanup.py'
SOURCE=ROOT/'integration/carpatic/settings/lib/cset/pages/system.py'
spec=importlib.util.spec_from_file_location('tested_cache',MODULE)
cache=importlib.util.module_from_spec(spec);sys.modules[spec.name]=cache;spec.loader.exec_module(cache)


def handlers():
    cls=next(n for n in ast.parse(SOURCE.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='StoragePage')
    body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in {'clear_cache','_cache_done'}]
    ns={'cache_cleanup':cache}
    node=ast.ClassDef(name='Page',bases=[],keywords=[],body=body,decorator_list=[])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),str(SOURCE),'exec'),ns)
    return ns,ns['Page']


class Cleanup(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='cache proof ');self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name);self.directory=self.home/'custom cache ț';self.directory.mkdir()
        self.env=patch.dict(os.environ,{'HOME':str(self.home),'XDG_CACHE_HOME':str(self.directory)});self.env.start();self.addCleanup(self.env.stop)
    def fill(self):
        for name in ('thumbnails','carpatic/thumbs'):
            folder=self.directory/name;folder.mkdir(parents=True)
            (folder/'.hidden ș').write_text('thumbnail')
        (self.directory/'keep').write_text('unrelated')
    def test_custom_absolute_cache_unicode_and_unrelated_preserved(self):
        self.fill();result=cache.clear_thumbnails()
        self.assertEqual(result.failed,())
        self.assertFalse((self.directory/'thumbnails').exists());self.assertFalse((self.directory/'carpatic/thumbs').exists())
        self.assertEqual((self.directory/'keep').read_text(),'unrelated');self.assertTrue((self.directory/'carpatic').is_dir())
    def test_relative_xdg_uses_home_default(self):
        default=self.home/'.cache';default.mkdir();(default/'thumbnails').mkdir()
        os.environ['XDG_CACHE_HOME']='relative/path'
        self.assertEqual(cache.cache_directory(),str(default));self.assertEqual(cache.clear_thumbnails().failed,())
        self.assertFalse((default/'thumbnails').exists())
    def test_absent_directory_is_successful_noop(self):
        os.environ['XDG_CACHE_HOME']=str(self.home/'missing')
        self.assertEqual(cache.clear_thumbnails().failed,());self.assertFalse((self.home/'missing').exists())
    def test_target_symlinks_unlinked_without_following_targets(self):
        outside=self.home/'outside';outside.mkdir();(outside/'valuable').write_text('keep')
        (self.directory/'thumbnails').symlink_to(outside,target_is_directory=True)
        (self.directory/'carpatic').mkdir();(self.directory/'carpatic/thumbs').symlink_to(outside,target_is_directory=True)
        self.assertEqual(cache.clear_thumbnails().failed,())
        self.assertFalse((self.directory/'thumbnails').is_symlink());self.assertFalse((self.directory/'carpatic/thumbs').is_symlink())
        self.assertEqual((outside/'valuable').read_text(),'keep')
    def test_nested_parent_symlink_is_refused(self):
        outside=self.home/'outside';outside.mkdir();(outside/'thumbs').mkdir();(outside/'thumbs/keep').write_text('keep')
        (self.directory/'carpatic').symlink_to(outside,target_is_directory=True)
        result=cache.clear_thumbnails();self.assertEqual(result.failed,('Carpathian thumbnails',))
        self.assertEqual((outside/'thumbs/keep').read_text(),'keep')
    def test_declared_cache_root_symlink_is_resolved_and_preserved(self):
        self.fill();link=self.home/'link';link.symlink_to(self.directory,target_is_directory=True)
        os.environ['XDG_CACHE_HOME']=str(link)
        self.assertEqual(cache.cache_directory(),str(self.directory))
        self.assertEqual(cache.clear_thumbnails().failed,())
        self.assertTrue(link.is_symlink());self.assertEqual((self.directory/'keep').read_text(),'unrelated')
        self.assertFalse((self.directory/'thumbnails').exists())
    def test_relocated_home_ancestor_symlink_uses_intended_cache(self):
        actual=self.home/'actual-home';actual.mkdir();default=actual/'.cache';default.mkdir()
        (default/'thumbnails').mkdir();(default/'thumbnails/file').write_text('cache')
        (default/'keep').write_text('keep')
        home_link=self.home/'home-link';home_link.symlink_to(actual,target_is_directory=True)
        os.environ['HOME']=str(home_link);os.environ.pop('XDG_CACHE_HOME',None)
        self.assertEqual(cache.cache_directory(),str(default))
        self.assertEqual(cache.clear_thumbnails().failed,())
        self.assertTrue(home_link.is_symlink());self.assertEqual((default/'keep').read_text(),'keep')
        self.assertFalse((default/'thumbnails').exists())
    def test_declared_root_resolving_to_filesystem_root_is_refused(self):
        link=self.home/'root-link';link.symlink_to('/',target_is_directory=True)
        os.environ['XDG_CACHE_HOME']=str(link)
        self.assertEqual(cache.clear_thumbnails().failed,('cache directory',))
        self.assertTrue(link.is_symlink())
    def test_permission_failure_remains_actionable_and_other_target_clears(self):
        self.fill();original=cache.shutil.rmtree
        def remove(name,**kwargs):
            if name=='thumbnails':raise PermissionError('injected')
            return original(name,**kwargs)
        with patch.object(cache.shutil,'rmtree',side_effect=remove) as mocked:
            mocked.avoids_symlink_attacks=True
            result=cache.clear_thumbnails()
        self.assertEqual(result.failed,('thumbnails',));self.assertTrue((self.directory/'thumbnails').exists())
        self.assertFalse((self.directory/'carpatic/thumbs').exists());self.assertIn('Could not clear',cache.status_text(result))
    def test_io_failure_and_regeneration_never_report_cleared(self):
        (self.directory/'thumbnails').write_text('cache')
        original=cache.os.unlink
        def regenerate(name,**kwargs):
            original(name,**kwargs)
            fd=os.open(name,os.O_WRONLY|os.O_CREAT,0o600,dir_fd=kwargs['dir_fd']);os.close(fd)
        with patch.object(cache.os,'unlink',side_effect=OSError('injected')):
            self.assertEqual(cache.clear_thumbnails().failed,('thumbnails',))
        with patch.object(cache.os,'unlink',side_effect=regenerate):
            result=cache.clear_thumbnails()
        self.assertEqual(result.failed,('thumbnails',));self.assertTrue((self.directory/'thumbnails').exists())
    def test_unsafe_rmtree_platform_fails_closed(self):
        self.fill()
        with patch.object(cache.shutil.rmtree,'avoids_symlink_attacks',False):result=cache.clear_thumbnails()
        self.assertEqual(len(result.failed),2);self.assertTrue((self.directory/'thumbnails').exists())


class Handler(unittest.TestCase):
    def test_busy_worker_completion_and_retry_after_error(self):
        ns,Page=handlers();page=Page();page._cache_busy=False;queued=[]
        class Button:
            def set_sensitive(self,v):self.sensitive=v
        class Row:
            buttons=[Button()]
            def set_busy(self,v):self.busy=v
            def set_sub(self,v):self.sub=v
        page.cache_row=Row();ns['su']=SimpleNamespace(bg=lambda work,done:queued.append((work,done)))
        page.clear_cache();page.clear_cache();self.assertEqual(len(queued),1)
        self.assertIs(queued[0][0],cache.clear_thumbnails);self.assertFalse(page.cache_row.buttons[0].sensitive)
        queued.pop()[1](cache.CleanupResult(('thumbnails',)))
        self.assertTrue(page.cache_row.buttons[0].sensitive);self.assertIn('Could not clear',page.cache_row.sub)
        page.clear_cache();queued.pop()[1](cache.CleanupResult())
        self.assertIn('Cached thumbnails cleared',page.cache_row.sub)

if '--gtk' in sys.argv:
    sys.argv.remove('--gtk')
    import re,time
    tree=ast.parse((ROOT/'tests/notes-gui.py').read_text())
    guard=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='guard')
    exec(compile(ast.Module(body=[guard],type_ignores=[]),'private-display-guard','exec'),globals())
    guard()
    sys.path.insert(0,str(ROOT/'integration/carpatic/settings/lib'))
    from cset import ui,sysutil
    from gi.repository import Gtk,GLib
    class ActualGTK(unittest.TestCase):
        def test_real_button_worker_error_then_success_preserves_unrelated_cache(self):
            ns,Page=handlers();page=Page();page._cache_busy=False;ns['su']=sysutil
            window=Gtk.Window();self.addCleanup(window.destroy)
            page.cache_row=ui.ButtonRow('Clear cached thumbnails','','Clear',page.clear_cache)
            window.add(page.cache_row);window.show_all()
            def wait():
                deadline=time.monotonic()+3;context=GLib.MainContext.default()
                while page._cache_busy and time.monotonic()<deadline:
                    while context.pending():context.iteration(False)
                    time.sleep(.01)
                self.assertFalse(page._cache_busy)
            with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'XDG_CACHE_HOME':directory}):
                root=Path(directory);(root/'thumbnails').mkdir();(root/'thumbnails/file').write_text('cache');(root/'unrelated').write_text('keep')
                with patch.object(cache,'_remove',side_effect=PermissionError('controlled failure')):
                    page.cache_row.buttons[0].clicked();self.assertFalse(page.cache_row.buttons[0].get_sensitive());wait()
                self.assertTrue(page.cache_row.buttons[0].get_sensitive())
                self.assertTrue((root/'thumbnails/file').exists())
                page.cache_row.buttons[0].clicked();wait()
                self.assertFalse((root/'thumbnails').exists());self.assertEqual((root/'unrelated').read_text(),'keep')
                self.assertTrue(page.cache_row.buttons[0].get_sensitive())

if __name__=='__main__':unittest.main(verbosity=2)
