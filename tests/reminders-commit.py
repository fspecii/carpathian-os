#!/usr/bin/env python3
"""Actual temporary storage commits and truthful post-replace failures."""
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'integration/carpatic/reminders/lib'))
from carpatic_reminders import store

class Commits(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=store.Store(Path(self.tmp.name)/'reminders.json')
        self.original=self.store.add('Original')
    def failing_sync(self,directory):
        original=os.fsync
        def fail(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode)==directory:raise OSError('injected sync failure')
            return original(fd)
        return patch.object(store.os,'fsync',side_effect=fail)
    def test_file_sync_failure_preserves_old_bytes(self):
        before=self.store.path.read_bytes()
        with self.failing_sync(False),self.assertRaises(store.StoreError):self.store.add('Not committed')
        self.assertEqual(self.store.path.read_bytes(),before)
        self.assertEqual(list(self.store.path.parent.glob('.reminders-*')),[])
    def test_add_directory_failure_carries_applied_identity_and_list(self):
        with self.failing_sync(True),self.assertRaises(store.StoreCommitUncertain) as caught:self.store.add('Applied',completed=True)
        error=caught.exception;self.assertEqual(error.operation,'add');self.assertEqual(error.item['title'],'Applied');self.assertTrue(error.item['completed'])
        self.assertEqual(error.items,self.store.list());self.assertEqual(len(error.items),2)
        self.assertIn(error.item,error.items)
    def test_update_directory_failure_carries_applied_revision(self):
        with self.failing_sync(True),self.assertRaises(store.StoreCommitUncertain) as caught:self.store.update(self.original['id'],title='Changed')
        error=caught.exception;self.assertEqual(error.operation,'update');self.assertEqual(error.item['id'],self.original['id']);self.assertEqual(error.item['title'],'Changed')
        self.assertEqual(error.items,self.store.list())
    def test_delete_directory_failure_carries_actual_remaining_list(self):
        with self.failing_sync(True),self.assertRaises(store.StoreCommitUncertain) as caught:self.store.delete(self.original['id'])
        self.assertEqual(caught.exception.operation,'delete');self.assertIsNone(caught.exception.item);self.assertEqual(caught.exception.items,[]);self.assertEqual(self.store.list(),[])
    def test_directory_open_failure_after_replace_is_uncertain(self):
        real_open=os.open
        def fail(path,flags,*args,**kwargs):
            if flags & os.O_DIRECTORY:raise OSError('injected directory open failure')
            return real_open(path,flags,*args,**kwargs)
        with patch.object(store.os,'open',side_effect=fail),self.assertRaises(store.StoreCommitUncertain) as caught:self.store.update(self.original['id'],title='Applied before directory open')
        self.assertEqual(caught.exception.item,self.store.list()[0])
    def test_completed_creation_uses_one_write(self):
        with patch.object(self.store,'_write',wraps=self.store._write) as write:item=self.store.add('Completed',completed=True)
        self.assertEqual(write.call_count,1);self.assertTrue(item['completed']);self.assertIn(item,self.store.list())
    def test_completed_requires_actual_boolean(self):
        before=self.store.path.read_bytes()
        for completed in (1,'yes',None):
            with self.subTest(completed=completed),self.assertRaises(store.StoreError):self.store.add('Invalid',completed=completed)
        self.assertEqual(self.store.path.read_bytes(),before)
if __name__=='__main__':unittest.main()
