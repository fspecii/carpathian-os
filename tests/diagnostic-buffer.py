#!/usr/bin/env python3
"""Compile the independent ring and test disabled, exclusive, capacity/ordering semantics."""
import os,pathlib,subprocess,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
import importlib.util
spec=importlib.util.spec_from_file_location('builder',ROOT/'scripts/build-picom-diagnostic.py');builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
class Buffer(unittest.TestCase):
 def test_animation_bits(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d);(p/'carpatic_diag.h').write_text(builder.HEADER);(p/'ring.c').write_text(builder.SOURCE)
   (p/'main.c').write_text('#include "carpatic_diag.h"\nint main(void){cd_init();if(cd_enabled())cd_event(22,17,cd_double_bits(-0.0),cd_double_bits(0.035),1);return 0;}')
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(p/'main.c'),str(p/'ring.c'),'-o',str(p/'probe')],check=True)
   env=dict(os.environ);env.pop('CARPATIC_PICOM_DIAGNOSTIC',None)
   subprocess.run([str(p/'probe')],env=env,check=True);self.assertFalse((p/'out').exists())
   env['CARPATIC_PICOM_DIAGNOSTIC']=str(p/'out');subprocess.run([str(p/'probe')],env=env,check=True)
   record=(p/'out').read_text().splitlines()[2].split(',')
   import struct
   self.assertEqual(record[3:5],['22','17']);self.assertEqual(int(record[5]),1<<63)
   self.assertEqual(struct.unpack('=d',struct.pack('=Q',int(record[6])))[0],0.035)
   self.assertEqual(record[7],'1')
 def test_ring(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d);(p/'carpatic_diag.h').write_text(builder.HEADER);(p/'ring.c').write_text(builder.SOURCE)
   (p/'main.c').write_text('#include "carpatic_diag.h"\nint main(void){cd_init();cd_render_begin(17);for(int i=0;i<65540;i++)cd_event(4,i,2,3,0);return 0;}')
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(p/'main.c'),str(p/'ring.c'),'-o',str(p/'probe')],check=True)
   env=dict(os.environ);env.pop('CARPATIC_PICOM_DIAGNOSTIC',None)
   subprocess.run([str(p/'probe')],env=env,check=True);self.assertFalse((p/'out').exists())
   env['CARPATIC_PICOM_DIAGNOSTIC']=str(p/'out');subprocess.run([str(p/'probe')],env=env,check=True)
   lines=(p/'out').read_text().splitlines();self.assertIn('count=65536 overflow=5',lines[0]);self.assertEqual(len(lines),65538)
   self.assertEqual(lines[2].split(',')[1],'1');self.assertEqual(lines[-1].split(',')[0],'65535');self.assertEqual((p/'out').stat().st_mode&0o777,0o600)
   before=(p/'out').read_bytes();subprocess.run([str(p/'probe')],env=env,check=True);self.assertEqual(before,(p/'out').read_bytes())
   (p/'link').symlink_to(p/'out');env['CARPATIC_PICOM_DIAGNOSTIC']=str(p/'link');subprocess.run([str(p/'probe')],env=env,check=True);self.assertEqual(before,(p/'out').read_bytes())
if __name__=='__main__':unittest.main()
