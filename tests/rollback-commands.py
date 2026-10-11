#!/usr/bin/env python3
"""Actual recovery CLI with temporary files, simulated subvolumes and injected I/O failures.

Never mounts a filesystem, writes host /boot, or invokes real btrfs.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'integration/carpatic/compat/bin/carpatic-rollback'

class Recovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='carpathian-rollback-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.top = self.root/'top'; self.boot = self.root/'boot'; self.bin = self.root/'bin'
        self.top.mkdir(); self.boot.mkdir(); self.bin.mkdir()
        (self.top/'@').mkdir(); (self.top/'@/system').write_text('current system')
        (self.top/'@home').mkdir(); (self.top/'@home/file').write_text('personal file')
        (self.top/'@snapshots').mkdir()
        self.ident = '20260101-120000-manual'
        point = self.top/'@snapshots'/self.ident; point.mkdir(); (point/'system').write_text('selected system')
        (self.top/'@snapshots'/(self.ident+'.label')).write_text('selected point')
        saved = self.top/'@snapshots'/(self.ident+'.boot'); saved.mkdir()
        for name in ('vmlinuz-lts','initramfs-lts','boot.conf'):
            (self.boot/name).write_text('CURRENT '+name); (saved/name).write_text('SELECTED '+name)
        self.index = self.root/'index'; self.index.write_text('previous index')
        self.env = dict(os.environ, PATH=str(self.bin)+':/usr/bin:/bin', CARPATIC_TOP=str(self.top),
                        CARPATIC_BOOT=str(self.boot), CARPATIC_INDEX=str(self.index), TEST_ROOT=str(self.root),
                        TEST_TOP=str(self.top), TEST_BOOT=str(self.boot), TEST_ID=self.ident, FAILURE='none', NESTED='')
        self.stub('id', '#!/bin/sh\n[ "$1" = -u ] && echo 0\n')
        self.stub('btrfs', '#!'+sys_python()+'\n'+BTRFS)
        for command in ('cp','mv'):
            self.stub(command, '#!'+sys_python()+'\nCOMMAND='+repr(command)+'\n'+IO)
    def stub(self,name,body):
        path = self.bin/name; path.write_text(body); path.chmod(0o755)
    def invoke(self,action='restore',failure='none'):
        self.env['FAILURE']=failure
        args=[action,self.ident] if action=='restore' else [action,'manual']
        return subprocess.run(['sh',str(SCRIPT),*args],env=self.env,capture_output=True,text=True,timeout=15)
    def original_boot(self):
        for name in ('vmlinuz-lts','initramfs-lts','boot.conf'):
            self.assertEqual((self.boot/name).read_text(),'CURRENT '+name)
    def preserved_root(self):
        self.assertEqual((self.top/'@/system').read_text(),'current system')
        self.assertEqual((self.top/'@home/file').read_text(),'personal file')
    def clean_staging(self):
        self.assertFalse(list(self.boot.glob('.carpathian-*')))
        self.assertFalse(list((self.top/'@snapshots').glob('.pending-*')))
        self.assertFalse(list(self.top.glob('@new-*')))
    def add_nested(self):
        self.env['NESTED']='swap,extra'
        for name in ('swap','extra'):
            (self.top/'@'/name).mkdir(); (self.top/'@'/name/'payload').write_text(name+' payload')
            (self.top/'@snapshots'/self.ident/name).mkdir()
    def test_snapshot_copy_failure_not_published(self):
        result=self.invoke('snapshot','snapshot-copy')
        self.assertNotEqual(result.returncode,0); self.assertNotIn('Snapshot saved',result.stdout)
        self.assertEqual(sorted(p.name for p in (self.top/'@snapshots').iterdir()),[self.ident,self.ident+'.boot',self.ident+'.label'])
        self.original_boot(); self.preserved_root(); self.clean_staging()
    def test_snapshot_missing_pair_refused(self):
        (self.boot/'initramfs-lts').unlink()
        result=self.invoke('snapshot')
        self.assertNotEqual(result.returncode,0); self.assertIn('complete',result.stderr)
        self.assertNotIn('Snapshot saved',result.stdout)
        self.assertEqual(len(list((self.top/'@snapshots').glob('*.label'))),1)
    def test_successful_snapshot_has_verified_boot_pair_and_index(self):
        result=self.invoke('snapshot'); self.assertEqual(result.returncode,0,result.stderr)
        labels=list((self.top/'@snapshots').glob('*.label')); self.assertEqual(len(labels),2)
        created=next(p.stem for p in labels if p.stem!=self.ident)
        self.assertEqual((self.top/'@snapshots'/(created+'.boot')/'vmlinuz-lts').read_bytes(),(self.boot/'vmlinuz-lts').read_bytes())
        self.assertIn(created,self.index.read_text()); self.clean_staging()
    def test_restore_missing_boot_bundle_refused_before_mutation(self):
        (self.top/'@snapshots'/(self.ident+'.boot')/'initramfs-lts').unlink()
        result=self.invoke(); self.assertNotEqual(result.returncode,0)
        self.assertIn('Nothing was changed',result.stderr); self.original_boot(); self.preserved_root(); self.clean_staging()
    def test_restore_missing_current_boot_configuration_is_refused(self):
        (self.top/'@snapshots'/(self.ident+'.boot')/'boot.conf').unlink()
        result=self.invoke(); self.assertNotEqual(result.returncode,0)
        self.assertIn('missing the boot configuration',result.stderr)
        self.original_boot(); self.preserved_root(); self.clean_staging()

    def test_restore_stage_copy_failure_precedes_root_changes(self):
        result=self.invoke(failure='restore-stage-copy'); self.assertNotEqual(result.returncode,0)
        self.original_boot(); self.preserved_root(); self.clean_staging()
        self.assertEqual(len(list((self.top/'@snapshots').glob('*.label'))),1)
    def test_safety_snapshot_failure_cleans_selected_boot_stage(self):
        result=self.invoke(failure='safety-snapshot'); self.assertNotEqual(result.returncode,0)
        self.original_boot(); self.preserved_root(); self.clean_staging()
    def test_root_and_boot_commit_failures_undo_nested_subvolumes(self):
        for failure in ('root-aside','root-activate','boot-commit','nested-transfer'):
            with self.subTest(failure=failure):
                # Each case gets its own untouched fixture.
                nested=Recovery('test_successful_restore_keeps_nested_and_home'); nested.setUp()
                try:
                    nested.add_nested(); result=nested.invoke(failure=failure)
                    self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
                    self.assertNotIn('Done.',result.stdout)
                    nested.original_boot(); nested.preserved_root(); nested.clean_staging()
                    for name in ('swap','extra'): self.assertEqual((nested.top/'@'/name/'payload').read_text(),name+' payload')
                finally: nested.doCleanups()
    def test_interrupt_after_nested_rename_undoes_before_cleanup(self):
        self.add_nested(); result=self.invoke(failure='nested-interrupt')
        self.assertEqual(result.returncode,130,result.stdout+result.stderr)
        self.assertNotIn('Done.',result.stdout)
        self.original_boot(); self.preserved_root(); self.clean_staging()
        for name in ('swap','extra'): self.assertEqual((self.top/'@'/name/'payload').read_text(),name+' payload')

    def test_successful_restore_keeps_nested_and_home(self):
        self.add_nested(); result=self.invoke(); self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual((self.top/'@/system').read_text(),'selected system')
        for name in ('swap','extra'): self.assertEqual((self.top/'@'/name/'payload').read_text(),name+' payload')
        self.assertEqual((self.top/'@home/file').read_text(),'personal file')
        for name in ('vmlinuz-lts','initramfs-lts','boot.conf'): self.assertEqual((self.boot/name).read_text(),'SELECTED '+name)
        self.assertIn('Done.',result.stdout); self.clean_staging()
    def test_undo_failure_keeps_recovery_data_and_warns_no_restart(self):
        self.add_nested(); result=self.invoke(failure='partial-root')
        self.assertNotEqual(result.returncode,0); self.assertNotIn('Done.',result.stdout)
        self.assertIn('partial restore failure; do not restart',result.stderr)
        self.assertTrue(list(self.boot.glob('.carpathian-restore-*')))
        self.assertTrue(list((self.top/'@snapshots').glob('replaced-*')))
        self.assertTrue(list(self.top.glob('@new-*/swap/payload')))
    def configure_menu(self):
        content='/Carpathian\n    kernel_cmdline: rootflags=subvol=@ quiet\n'
        (self.boot/'limine.conf').write_text(content)
        (self.top/'@snapshots'/(self.ident+'.boot')/'limine.conf').write_text(content)
        (self.boot/'snapshots').mkdir(); (self.boot/'snapshots/old-file').write_text('old menu files')
        return content
    def test_menu_copy_and_commit_failures_do_not_publish_success(self):
        for failure in ('menu-copy','menu-second-copy','menu-commit','index-commit'):
            with self.subTest(failure=failure):
                nested=Recovery('test_successful_restore_keeps_nested_and_home'); nested.setUp()
                try:
                    config=nested.configure_menu(); result=nested.invoke('snapshot',failure)
                    self.assertNotEqual(result.returncode,0); self.assertNotIn('Snapshot saved',result.stdout)
                    self.assertEqual((nested.boot/'limine.conf').read_text(),config)
                    self.assertEqual((nested.boot/'snapshots/old-file').read_text(),'old menu files')
                    self.assertEqual(nested.index.read_text(),'previous index')
                    self.assertFalse(list((nested.top/'@snapshots').glob('*.rw')))
                    nested.original_boot(); nested.preserved_root(); nested.clean_staging()
                finally: nested.doCleanups()
    def test_index_rename_interrupt_preserves_published_generation(self):
        for menu in (False, True):
            with self.subTest(menu=menu):
                fixture=Recovery(); fixture.setUp()
                try:
                    if menu: fixture.configure_menu()
                    result=fixture.invoke('snapshot','index-interrupt')
                    self.assertEqual(result.returncode,130,result.stderr)
                    labels=list((fixture.top/'@snapshots').glob('*.label'))
                    self.assertEqual(len(labels),2)
                    for label in labels:
                        self.assertIn(label.stem,fixture.index.read_text())
                        self.assertTrue((fixture.top/'@snapshots'/(label.stem+'.boot')/'initramfs-lts').exists())
                        if menu: self.assertTrue((fixture.boot/'snapshots'/label.stem/'vmlinuz-lts').exists())
                    fixture.original_boot(); fixture.preserved_root(); fixture.clean_staging()
                finally: fixture.doCleanups()
    def test_final_restore_index_interrupt_accepts_matching_generation(self):
        self.add_nested(); self.configure_menu()
        result=self.invoke(failure='restore-index-interrupt')
        self.assertEqual(result.returncode,130,result.stderr)
        self.assertEqual((self.top/'@/system').read_text(),'selected system')
        for name in ('vmlinuz-lts','initramfs-lts','boot.conf'): self.assertEqual((self.boot/name).read_text(),'SELECTED '+name)
        for name in ('swap','extra'): self.assertEqual((self.top/'@'/name/'payload').read_text(),name+' payload')
        self.clean_staging()
    def test_repeated_menu_undo_preserves_already_restored_entries(self):
        config=self.configure_menu(); (self.boot/'limine').mkdir()
        (self.boot/'limine/limine.conf').write_text(config)
        result=self.invoke('snapshot','double-undo')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual((self.boot/'limine.conf').read_text(),config)
        self.assertEqual((self.boot/'limine/limine.conf').read_text(),config)
        self.assertEqual((self.boot/'snapshots/old-file').read_text(),'old menu files')
        self.original_boot(); self.preserved_root(); self.clean_staging()

    def test_menu_success_pairs_correct_kernel_flavor(self):
        self.configure_menu()
        for base in (self.boot,self.top/'@snapshots'/(self.ident+'.boot')):
            (base/'vmlinuz-lts').rename(base/'vmlinuz-virt'); (base/'initramfs-lts').rename(base/'initramfs-virt')
        result=self.invoke('snapshot'); self.assertEqual(result.returncode,0,result.stderr)
        config=(self.boot/'limine.conf').read_text()
        self.assertIn('/vmlinuz-virt',config); self.assertIn('/initramfs-virt',config)
        self.assertNotIn('/initramfs-lts',config); self.clean_staging()
    def test_inherited_lock_validation_and_kernel_exclusion(self):
        import fcntl
        lock=self.top/'.carpathian-rollback.lock'; lock.touch()
        # Explicit inherited mode rejects absent and wrong descriptors.
        result=subprocess.run(['sh',str(SCRIPT),'--inherit-lock','snapshot','manual'],env=self.env,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        for target in (self.root/'wrong-lock',lock):
            target.touch()
            with target.open('w') as stream:
                result=subprocess.run(['sh','-c','exec 9>"$1"; exec sh "$2" --inherit-lock snapshot manual','test',str(target),str(SCRIPT)],env=self.env,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode==0,target==lock,result.stderr)
        with lock.open('w') as owner:
            fcntl.flock(owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
            result=subprocess.run(['sh','-c','exec 9>"$1"; exec sh "$2" --inherit-lock snapshot manual','test',str(lock),str(SCRIPT)],env=self.env,capture_output=True,text=True,timeout=15)
            self.assertNotEqual(result.returncode,0); self.assertIn('another restore-point',result.stderr)

    def test_traversal_id_refused(self):
        self.ident='../@home'; result=self.invoke()
        self.assertNotEqual(result.returncode,0); self.assertIn('invalid restore point',result.stderr)
        self.preserved_root(); self.original_boot()


def sys_python(): return shutil.which('python3')

BTRFS=r'''
import os,sys,pathlib,shutil
args=sys.argv[1:]; root=pathlib.Path(os.environ['TEST_ROOT']); failure=os.environ['FAILURE']
with (root/'commands').open('a') as stream: stream.write('btrfs '+' '.join(args)+'\n')
if args[:2]==['subvolume','create']:
 pathlib.Path(args[-1]).mkdir(); sys.exit(0)
if args[:2]==['subvolume','delete']:
 shutil.rmtree(args[-1]); sys.exit(0)
if args[:2]==['subvolume','list']:
 for name in filter(None,os.environ.get('NESTED','').split(',')): print('ID 2 gen 3 top level 5 path @/'+name)
 sys.exit(0)
if args[:2]==['subvolume','snapshot']:
 if failure=='safety-snapshot' and '-r' in args: sys.exit(1)
 source,destination=map(pathlib.Path,args[-2:]); shutil.copytree(source,destination)
 for name in filter(None,os.environ.get('NESTED','').split(',')):
  if (destination/name).is_dir(): shutil.rmtree(destination/name); (destination/name).mkdir()
 sys.exit(0)
sys.exit(1)
'''
IO=r'''
import os,sys,pathlib,subprocess
args=sys.argv[1:]; source,destination=args[-2:]; root=pathlib.Path(os.environ['TEST_ROOT']); boot=os.environ['TEST_BOOT']; top=os.environ['TEST_TOP']; failure=os.environ['FAILURE']; flag=root/'fault-fired'
fail=False
if COMMAND=='mv' and destination==str(root/'index') and failure in ('index-interrupt','restore-index-interrupt'):
 countfile=root/'index-count'; count=int(countfile.read_text())+1 if countfile.exists() else 1; countfile.write_text(str(count))
 if failure=='index-interrupt' or count==2:
  import signal
  result=subprocess.call(['/bin/mv',*args]); os.kill(os.getppid(),signal.SIGTERM); sys.exit(result)
if failure=='double-undo' and COMMAND=='mv':
 if destination==str(root/'index'): sys.exit(1)
 if '/old/limine/limine.conf' in source and not flag.exists(): flag.write_text('undo failed once'); sys.exit(1)
if COMMAND=='mv' and failure=='nested-interrupt' and source==top+'/@/extra':
 import signal
 result=subprocess.call(['/bin/mv',*args])
 os.kill(os.getppid(),signal.SIGTERM)
 sys.exit(result)
if COMMAND=='cp':
 fail=(failure=='snapshot-copy' and '.pending-' in destination and destination.endswith('initramfs-lts')) or (failure=='restore-stage-copy' and '.carpathian-restore-' in destination and destination.endswith('initramfs-lts')) or (failure=='menu-copy' and '.carpathian-menu-' in destination and destination.endswith('initramfs-lts')) or (failure=='menu-second-copy' and '.carpathian-menu-' in destination and os.environ['TEST_ID'] in destination)
else:
 fail=(failure=='root-aside' and source==top+'/@' and '/replaced-' in destination) or (failure in ('root-activate','partial-root') and '/@new-' in source and destination==top+'/@') or (failure=='boot-commit' and '.carpathian-restore-' in source and '/new/' in source and destination==boot+'/initramfs-lts') or (failure=='nested-transfer' and source==top+'/@/extra') or (failure=='menu-commit' and '.carpathian-menu-' in source and '/new/' in source and destination==boot+'/limine.conf') or (failure=='index-commit' and destination==str(root/'index'))
 if failure=='partial-root' and '/replaced-' in source and destination==top+'/@': sys.exit(1)
if fail and not flag.exists(): flag.write_text('injected'); print('injected '+COMMAND+' failure',file=sys.stderr); sys.exit(1)
sys.exit(subprocess.call(['/bin/'+COMMAND,*args]))
'''

if __name__=='__main__': unittest.main(verbosity=2)
