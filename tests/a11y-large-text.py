#!/usr/bin/env python3
"""Actual POSIX a11y/appearance/lib scripts under owned HOME and command PATH."""
import os, shutil, subprocess, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class LargeText(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='carpatic-large-text-');self.addCleanup(self.temp.cleanup)
  self.base=Path(self.temp.name);self.home=self.base/'home';self.bin=self.base/'bin';self.cfg=self.home/'.config/carpatic'
  self.bin.mkdir();self.cfg.mkdir(parents=True);self.home.chmod(0o700)
  self.settings=self.cfg/'settings.conf';self.state=self.cfg/'a11y.env';self.snapshot=self.cfg/'large-text.snapshot';self.log=self.base/'applies'
  for name in ('sh','mkdir','rmdir','dirname','grep','sed','tail','tr','awk','mktemp','rm','sleep','flock','cat'):
   executable=shutil.which(name)
   if executable:(self.bin/name).symlink_to(executable)
  self.real_mv=shutil.which('mv')
  (self.bin/'mv').write_text('''#!/bin/sh
for last do :; done
case "$MV_FAILURE:$last" in state:*/a11y.env|snapshot:*/large-text.snapshot|restore:*/settings.conf) exit 17;; esac
exec "'''+self.real_mv+'''" "$@"
''');(self.bin/'mv').chmod(0o700)
  for name in ('carpatic-appearance','carpatic-lib'):(self.bin/name).symlink_to(ROOT/'integration/carpatic/configurator/bin'/name)
  (self.bin/'carpatic-apply').write_text('''#!/bin/sh
printf 'apply\n' >> "$APPLY_LOG"
[ ! -e /proc/$$/fd/9 ] || { echo 'lock fd inherited' >&2; exit 19; }
[ -z "$APPLY_DELAY" ] || sleep "$APPLY_DELAY"
exit "$APPLY_RC"
''');(self.bin/'carpatic-apply').chmod(0o700)
  self.env=os.environ.copy()
  for name in ('DISPLAY','WAYLAND_DISPLAY','CARPATIC_CONFIG','XDG_CONFIG_HOME'):self.env.pop(name,None)
  self.env.update(HOME=str(self.home),PATH=str(self.bin),APPLY_LOG=str(self.log),APPLY_RC='0',APPLY_DELAY='',MV_FAILURE='')
  self.script=ROOT/'integration/carpatic/compat/bin/carpatic-a11y'
  self.state.write_text('HIGH_CONTRAST="on"\nLARGE_TEXT="off"\n')
 def effective(self,ui=10,mono=10,cursor=24,scale=100):
  (self.settings.parent/'appearance.env').write_text(f'UI_FONT="Fixture Font {ui}"\nMONO_FONT="Fixture Mono {mono}"\nCURSOR_SIZE="{cursor}"\nSCALE="{scale}"\n')
 def seed(self,values):
  self.effective()
  self.settings.write_text('THEME="fixture-current"\nUI_FONT="Fixture Font"\nBORDER_WIDTH="3"\n'+''.join(f'{key}="{value}"\n' for key,value in values.items()))
 def values(self):
  values={}
  if self.settings.exists():
   for line in self.settings.read_text().splitlines():
    if '=' in line:
     key,value=line.split('=',1);values[key]=value.strip('"')
  return values
 def call(self,action,ok=True):
  result=subprocess.run(['sh',str(self.script),'large-text',action],env=self.env,capture_output=True,text=True,timeout=8)
  self.assertEqual(result.returncode==0,ok,result.stderr)
  return result
 def untouched(self):
  values=self.values();self.assertEqual(values['THEME'],'fixture-current');self.assertEqual(values['UI_FONT'],'Fixture Font');self.assertEqual(values['BORDER_WIDTH'],'3');self.assertIn('HIGH_CONTRAST="on"',self.state.read_text())
 def test_custom_sizes_round_trip_and_repeated_on_capture_once(self):
  original={'UI_SIZE':'17','MONO_SIZE':'16','CURSOR_SIZE':'48'};self.seed(original);self.call('on');self.assertEqual([self.values()[k] for k in original],['19','18','56']);snapshot=self.snapshot.read_bytes();self.call('on');self.assertEqual(self.snapshot.read_bytes(),snapshot);self.assertEqual([self.values()[k] for k in original],['19','18','56'])
  self.call('off');self.assertEqual({k:self.values()[k] for k in original},original);self.assertFalse(self.snapshot.exists());self.untouched()
 def test_absent_empty_and_mixed_overrides_round_trip(self):
  for original in ({},{'UI_SIZE':'','MONO_SIZE':''},{'UI_SIZE':'19','CURSOR_SIZE':''},{'UI_SIZE':'default','MONO_SIZE':'0016'}):
   with self.subTest(original=original):
    self.seed(original);self.call('on');self.call('off');values=self.values()
    self.assertEqual({k:values[k] for k in ('UI_SIZE','MONO_SIZE','CURSOR_SIZE') if k in values},original);self.untouched()
 def test_computed_theme_defaults_scaled_cursor_and_relogin_stable(self):
  self.seed({});self.effective(ui=20,mono=18,cursor=96,scale=200);self.call('on')
  self.assertEqual([self.values()[k] for k in ('UI_SIZE','MONO_SIZE','CURSOR_SIZE')],['22','20','56'])
  snapshot=self.snapshot.read_bytes();self.effective(22,20,112,200);self.call('on');self.assertEqual(self.snapshot.read_bytes(),snapshot)
  self.call('off');self.assertFalse(any(k in self.values() for k in ('UI_SIZE','MONO_SIZE','CURSOR_SIZE')))
 def test_defaults_floor_and_fractional_cursor_rounding(self):
  self.seed({});self.effective(10,10,61,125);self.call('on')
  self.assertEqual([self.values()[k] for k in ('UI_SIZE','MONO_SIZE','CURSOR_SIZE')],['14','13','57'])
 def test_enlargement_cannot_shrink_larger_effective_sizes(self):
  original={'UI_SIZE':'17','MONO_SIZE':'16','CURSOR_SIZE':'48'}
  self.seed(original);self.effective(ui=24,mono=22,cursor=128,scale=200);self.call('on')
  self.assertEqual([self.values()[k] for k in ('UI_SIZE','MONO_SIZE','CURSOR_SIZE')],['26','24','72'])
  self.call('off');self.assertEqual({k:self.values()[k] for k in original},original)
 def test_v1_migration_preserves_originals_and_freezes_targets(self):
  self.seed({'UI_SIZE':'14','MONO_SIZE':'13','CURSOR_SIZE':'40'})
  self.snapshot.write_text('VERSION=1\nUI_SIZE=17\nMONO_SIZE=16\nCURSOR_SIZE=48\n')
  self.call('on');saved=self.snapshot.read_bytes();self.assertIn(b'UI_SIZE=17\n',saved);self.assertIn(b'TARGET_UI_SIZE=19\n',saved)
  self.call('on');self.assertEqual(self.snapshot.read_bytes(),saved);self.call('off');self.assertEqual(self.values()['UI_SIZE'],'17')
 def test_missing_malformed_effective_capture_is_nonzero_and_retains_originals(self):
  for content in ('','UI_FONT="Fixture Font nope"\n','UI_FONT="Fixture Font 999999999999999999999"\n'):
   with self.subTest(content=content):
    self.seed({'UI_SIZE':'17'});(self.settings.parent/'appearance.env').write_text(content)
    self.call('on',False);self.assertTrue(self.snapshot.exists());self.assertIn('UI_SIZE=17',self.snapshot.read_text());self.assertFalse(self.log.exists());self.snapshot.unlink()
 def test_unbounded_original_refused_without_apply(self):
  self.seed({'UI_SIZE':'999999999999999999999'});self.call('on',False);self.assertFalse(self.log.exists());self.assertTrue(self.snapshot.exists())
 def test_off_without_on_preserves_custom_and_skips_backend(self):
  self.seed({'UI_SIZE':'17'});before=self.settings.read_bytes();self.call('off');self.assertEqual(self.settings.read_bytes(),before);self.assertFalse(self.log.exists())
 def test_backend_failure_is_nonzero_retains_snapshot_and_retry(self):
  self.seed({'UI_SIZE':'17','MONO_SIZE':'16','CURSOR_SIZE':'48'});self.env['APPLY_RC']='12';result=self.call('on',False)
  self.assertTrue(self.snapshot.exists());self.assertIn('LARGE_TEXT="off"',self.state.read_text());self.assertIn('may already have changed',result.stderr)
  self.env['APPLY_RC']='0';self.call('off');self.assertEqual(self.values()['UI_SIZE'],'17');self.untouched()
 def test_restore_backend_failure_retains_on_state_and_snapshot(self):
  self.seed({'UI_SIZE':'17'});self.call('on');self.env['APPLY_RC']='12';self.call('off',False);self.assertTrue(self.snapshot.exists());self.assertIn('LARGE_TEXT="on"',self.state.read_text())
  self.env['APPLY_RC']='0';self.call('off');self.assertEqual(self.values()['UI_SIZE'],'17');self.assertNotIn('MONO_SIZE',self.values())
 def test_state_write_failure_retains_retry_snapshot(self):
  self.seed({'UI_SIZE':'17'});self.env['MV_FAILURE']='state';self.call('on',False);self.assertTrue(self.snapshot.exists());self.assertIn('LARGE_TEXT="off"',self.state.read_text())
  self.env['MV_FAILURE']='';self.call('on');self.env['MV_FAILURE']='state';self.call('off',False);self.assertTrue(self.snapshot.exists());self.assertIn('LARGE_TEXT="on"',self.state.read_text())
  self.env['MV_FAILURE']='';self.call('off');self.assertEqual(self.values()['UI_SIZE'],'17')
 def test_capture_write_failure_never_calls_backend(self):
  self.seed({'UI_SIZE':'17'});self.env['MV_FAILURE']='snapshot';self.call('on',False);self.assertFalse(self.snapshot.exists());self.assertFalse(self.log.exists());self.assertEqual(self.values()['UI_SIZE'],'17')
 def test_restore_settings_write_failure_retains_snapshot(self):
  self.seed({'UI_SIZE':'17'});self.call('on');self.env['MV_FAILURE']='restore';self.call('off',False);self.assertTrue(self.snapshot.exists());self.env['MV_FAILURE']='';self.call('off');self.assertEqual(self.values()['UI_SIZE'],'17')
 def test_capture_read_failure_and_invalid_value_do_not_apply(self):
  self.seed({'UI_SIZE':'17'});self.settings.chmod(0)
  try:self.call('on',False);self.assertFalse(self.log.exists())
  finally:self.settings.chmod(0o600)
  marker=self.base/'never-executed';self.seed({'UI_SIZE':'$(touch '+str(marker)+')'});self.call('on',False);self.assertFalse(marker.exists());self.assertFalse(self.log.exists())
 def test_legacy_migration_restores_only_validated_size_fields_without_eval(self):
  self.seed({'UI_SIZE':'14','MONO_SIZE':'13','CURSOR_SIZE':'40'});marker=self.base/'never-executed'
  self.state.write_text('HIGH_CONTRAST="on"\nLARGE_TEXT="on"\nLARGE_PREV="UI_SIZE=17 MONO_SIZE=16 CURSOR_SIZE=48 UI_FONT=$(touch '+str(marker)+') THEME=old-theme"\n')
  self.call('off');self.assertEqual(self.values()['UI_SIZE'],'17');self.assertEqual(self.values()['MONO_SIZE'],'16');self.assertEqual(self.values()['CURSOR_SIZE'],'48');self.assertFalse(marker.exists());self.assertNotIn('LARGE_PREV',self.state.read_text());self.untouched()
 def test_actual_get_legacy_format_scaled_cursor_and_literal_shell_text(self):
  self.seed({'UI_SIZE':'14','MONO_SIZE':'13','CURSOR_SIZE':'40'})
  self.effective(17,16,96,200)
  actual=subprocess.run(['carpatic-appearance','get'],env=self.env,capture_output=True,text=True,check=True).stdout
  marker=self.base/'never-executed'
  # Real original code collapsed command substitution and removed quotes on read.
  legacy=' '.join(actual.split())+f' EXTRA="`touch {marker}` $(touch {marker})"'
  self.state.write_text('HIGH_CONTRAST="on"\nLARGE_TEXT="on"\nLARGE_PREV="'+legacy+'"\n')
  self.call('on');self.assertEqual([self.values()[k] for k in ('UI_SIZE','MONO_SIZE','CURSOR_SIZE')],['19','18','56'])
  self.call('off');self.assertEqual([self.values()[k] for k in ('UI_SIZE','MONO_SIZE','CURSOR_SIZE')],['17','16','48']);self.assertFalse(marker.exists());self.untouched()
 def test_missing_computed_cache_and_failed_capture_backend(self):
  self.seed({});(self.settings.parent/'appearance.env').unlink();self.env['APPLY_RC']='12'
  self.call('on',False);self.assertTrue(self.snapshot.exists());self.assertIn('LARGE_TEXT="off"',self.state.read_text());self.assertNotIn('UI_SIZE',self.values())
 def test_invalid_legacy_retained_without_backend(self):
  self.seed({'UI_SIZE':'14'});self.state.write_text('LARGE_TEXT="on"\nLARGE_PREV="UI_SIZE=17 MONO_SIZE=bad CURSOR_SIZE=48"\n');before=self.state.read_bytes();self.call('off',False);self.assertEqual(self.state.read_bytes(),before);self.assertFalse(self.log.exists())
 def test_configuration_override_path_is_the_real_appearance_path(self):
  alternative=self.base/'alternate';alternative.mkdir();self.env['CARPATIC_CONFIG']=str(alternative);self.settings=alternative/'settings.conf';self.seed({'UI_SIZE':'21'});self.call('on');self.call('off');self.assertEqual(self.values()['UI_SIZE'],'21');self.assertNotIn('MONO_SIZE',self.values())
 def test_concurrent_on_transactions_serialize_original_capture(self):
  if not (self.bin/'flock').exists():self.skipTest('flock unavailable')
  self.seed({'UI_SIZE':'17'});self.env['APPLY_DELAY']='0.1'
  processes=[subprocess.Popen(['sh',str(self.script),'large-text','on'],env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
  try:
   for proc in processes:
    output,error=proc.communicate(timeout=8);self.assertEqual(proc.returncode,0,error)
  finally:
   for proc in processes:
    if proc.poll() is None:proc.kill();proc.wait()
  self.assertIn('UI_SIZE=17',self.snapshot.read_text());self.call('off');self.assertEqual(self.values()['UI_SIZE'],'17')
 def test_corrupt_snapshot_is_retained_without_backend_or_eval(self):
  self.seed({'UI_SIZE':'17'});self.call('on');before=self.log.read_bytes();marker=self.base/'never-executed'
  corrupt='VERSION=1\nUI_SIZE=$(touch '+str(marker)+')\nMONO_SIZE=absent\nCURSOR_SIZE=empty\n'
  self.snapshot.write_text(corrupt);self.call('off',False);self.assertEqual(self.snapshot.read_text(),corrupt);self.assertEqual(self.log.read_bytes(),before);self.assertFalse(marker.exists());self.assertIn('LARGE_TEXT="on"',self.state.read_text())
 def test_snapshot_is_private_and_failed_atomic_temp_is_cleaned(self):
  self.seed({'UI_SIZE':'17'});self.env['MV_FAILURE']='state';self.call('on',False)
  self.assertEqual(self.snapshot.stat().st_mode & 0o777,0o600)
  self.assertEqual(list(self.cfg.glob('.large-text-state.*')),[]);self.assertEqual(list(self.cfg.glob('.large-text-snapshot.*')),[])
 def test_missing_flock_uses_owned_lock_directory_and_cleans_it(self):
  if (self.bin/'flock').exists():(self.bin/'flock').unlink()
  self.seed({'UI_SIZE':'17'});self.call('on');self.call('off');self.assertFalse((self.cfg/'large-text.lock.d').exists())
if __name__=='__main__':unittest.main()
