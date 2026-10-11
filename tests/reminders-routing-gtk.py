#!/usr/bin/env python3
"""Actual second-process Reminders GApplication forwarding on a private bus."""
import ast
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
ROOT=Path(__file__).resolve().parents[1]
tree=ast.parse((ROOT/'tests/notes-gui.py').read_text())
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='guard'],type_ignores=[]),'private GTK guard','exec'))
guard()
sys.path.insert(0,str(ROOT/'integration/carpatic/reminders/lib'))


def primary(directory):
    from carpatic_reminders import app as production
    folder=Path(directory);state=folder/'state.json';calls=[];confirmations=[]
    original=production.RemindersApplication.do_command_line
    def confirm(parent):
        confirmations.append(parent.title.get_text())
        return (folder/'allow-discard').exists()
    production.confirm_discard=confirm
    def command(application,request):
        result=original(application,request)
        calls.append(list(request.get_arguments()))
        window=application.window
        count=len(calls)
        from gi.repository import GLib
        def settled():
            if window.busy:return True
            if count==1:
                window.title.set_text('Primary unsaved draft')
                window.notes.get_buffer().set_text('Preserve this text across processes')
            buffer=window.notes.get_buffer()
            snapshot={'pid':os.getpid(),'window':id(window),'calls':list(calls),'confirmations':list(confirmations),
                      'title':window.title.get_text(),'notes':buffer.get_text(buffer.get_start_iter(),buffer.get_end_iter(),True),
                      'day':window.day,'date':window.date.get_text(),'result':result,'busy':window.busy,
                      'pending_request':window.pending_request,'settled_request':count}
            temporary=folder/'state.tmp';temporary.write_text(json.dumps(snapshot));temporary.replace(state)
            return False
        GLib.timeout_add(10,settled)
        return result
    class ObservedApplication(production.RemindersApplication):
        def do_command_line(self,request):return command(self,request)
    return ObservedApplication().run(['carpatic-reminders'])


def secondary():
    from carpatic_reminders.app import run
    return run('2026-10-12',True)


class Routing(unittest.TestCase):
    def wait_state(self,path,count,process):
        deadline=time.monotonic()+6
        while time.monotonic()<deadline:
            if process.poll() is not None:raise AssertionError('Owned primary exited before forwarding')
            if path.exists():
                value=json.loads(path.read_text())
                if value.get('settled_request',0)>=count and not value['busy']:return value
            time.sleep(.02)
        raise AssertionError('Actual D-Bus forwarding did not reach primary')
    def test_second_process_new_keeps_draft_then_explicit_discard_uses_same_window(self):
        with tempfile.TemporaryDirectory(prefix='reminders-second-process-') as directory:
            folder=Path(directory);data=folder/'data';data.mkdir(mode=0o700)
            env=dict(os.environ,XDG_DATA_HOME=str(data))
            log=folder/'primary.log'
            with log.open('w') as output:
                process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--primary',directory],env=env,stdout=output,stderr=subprocess.STDOUT)
                try:
                    before=self.wait_state(folder/'state.json',1,process)
                    command=[sys.executable,str(Path(__file__).resolve()),'--secondary']
                    result=subprocess.run(command,env=env,capture_output=True,text=True,timeout=6)
                    self.assertEqual(result.returncode,0,result.stderr)
                    kept=self.wait_state(folder/'state.json',2,process)
                    self.assertEqual(kept['pid'],process.pid);self.assertEqual(kept['window'],before['window'])
                    self.assertEqual(kept['title'],before['title']);self.assertEqual(kept['notes'],before['notes'])
                    self.assertEqual(kept['day'],before['day']);self.assertEqual(kept['date'],before['date'])
                    self.assertEqual(kept['confirmations'],['Primary unsaved draft'])
                    self.assertIn('--new',kept['calls'][-1]);self.assertIn('2026-10-12',kept['calls'][-1])
                    (folder/'allow-discard').touch()
                    result=subprocess.run(command,env=env,capture_output=True,text=True,timeout=6)
                    self.assertEqual(result.returncode,0,result.stderr)
                    discarded=self.wait_state(folder/'state.json',3,process)
                    self.assertEqual(discarded['window'],before['window']);self.assertEqual(discarded['title'],'')
                    self.assertEqual(discarded['notes'],'');self.assertEqual(discarded['date'],'2026-10-12')
                    self.assertEqual(discarded['day'],'2026-10-12');self.assertEqual(len(discarded['confirmations']),2)
                    self.assertFalse((data/'carpatic/reminders/reminders.json').exists(),'Route silently saved discarded draft')
                    evidence=Path(os.environ.get('CARPATIC_ROUTING_EVIDENCE',ROOT/'artifacts/reminders-routing-review-20261011'))
                    evidence.mkdir(parents=True,exist_ok=True)
                    (evidence/'forwarding.json').write_text(json.dumps({'initial':before,'kept':kept,'discarded':discarded,'source_sha256':hashlib.sha256((ROOT/'integration/carpatic/reminders/lib/carpatic_reminders/app.py').read_bytes()).hexdigest()},indent=2))
                finally:
                    process.terminate()
                    try:process.wait(timeout=3)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
                if process.returncode not in (0,-15):self.fail(log.read_text())

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--primary':raise SystemExit(primary(sys.argv[2]))
    if len(sys.argv)>1 and sys.argv[1]=='--secondary':raise SystemExit(secondary())
    unittest.main()
