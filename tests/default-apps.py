#!/usr/bin/env python3
"""Actual discovery/default-page methods with isolated files and GTK-free rows."""
import ast, os, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]/'integration/carpatic/settings/lib/cset'

def load(path, names, namespace):
 tree=ast.parse(path.read_text());nodes=[n for n in tree.body if getattr(n,'name',None) in names or isinstance(n,ast.Assign) and any(getattr(t,'id',None) in names for t in n.targets)]
 exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),namespace)
 return namespace

class Discovery(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name)
  self.home=self.base/'home';self.user=self.base/'user';self.high=self.base/'high';self.low=self.base/'low'
  self.env=patch.dict(os.environ,{'XDG_DATA_HOME':str(self.user),'XDG_DATA_DIRS':str(self.high)+':relative:'+str(self.low)})
  self.env.start();self.addCleanup(self.env.stop)
  self.expand=patch('os.path.expanduser',side_effect=lambda p:str(self.home)+p[1:] if p.startswith('~') else p)
  self.expand.start();self.addCleanup(self.expand.stop)
  self.scan=load(ROOT/'sysutil.py',{'desktop_entries'},{'os':os})['desktop_entries']
 def entry(self,base,name,label='Viewer',extra=''):
  p=base/'applications'/name;p.parent.mkdir(parents=True,exist_ok=True)
  p.write_text('[Desktop Entry]\nType=Application\nName='+label+'\nExec=/bin/true %f\nMimeType=text/plain;\n'+extra)
 def test_custom_home_nested_id_and_precedence(self):
  self.entry(self.user,'vendor/viewer.desktop','User');self.entry(self.high,'vendor/viewer.desktop','System');self.entry(self.low,'second.desktop','Second')
  result={r[0]:r for r in self.scan()}
  self.assertEqual(result['vendor-viewer.desktop'][1],'User');self.assertEqual(result['second.desktop'][3],['text/plain'])
 def test_hidden_user_mask_applies_to_flattened_system_id(self):
  self.entry(self.user,'vendor-viewer.desktop',extra='Hidden=true\n');self.entry(self.high,'vendor/viewer.desktop')
  self.assertEqual(self.scan(),[])
 def test_system_precedence_and_hidden_mask(self):
  self.entry(self.high,'masked.desktop',extra='Hidden=true\n');self.entry(self.low,'masked.desktop');self.entry(self.high,'winner.desktop','First');self.entry(self.low,'winner.desktop','Last')
  self.assertEqual([(r[0],r[1]) for r in self.scan()],[('winner.desktop','First')])
 def test_empty_and_relative_data_home_use_default(self):
  self.entry(self.home/'.local/share','default.desktop')
  for value in ('','relative'):
   with patch.dict(os.environ,{'XDG_DATA_HOME':value}):self.assertEqual(self.scan()[0][0],'default.desktop')
 def test_missing_directory_and_nonapplication(self):
  self.entry(self.user,'link.desktop',extra='Type=Link\n') # first-key semantics: fixture below replaces Type
  p=self.user/'applications/link.desktop';p.write_text('[Desktop Entry]\nType=Link\nName=Link\n')
  self.assertEqual(self.scan(),[])

class Row:
 def __init__(self,title,sub='',options=(),value=None,on_change=None,**kwargs):self.title=title;self.sub=sub;self.options=options;self.value=value;self.on_change=on_change
 def set_value_quiet(self,value):self.value=value
class Defaults(unittest.TestCase):
 def page(self,default='',entries=None):
  self.rows=[];self.calls=[]
  su=SimpleNamespace(which=lambda _:False,desktop_entries=lambda:entries if entries is not None else [('viewer.desktop','Viewer','',['text/plain'],'true')],out=lambda *args:default,bg=lambda work,fill:fill(work()))
  ns=load(ROOT/'pages/system.py',{'CATEGORIES','candidates','AppsPage'},{'Page':object,'su':su,'PopupRow':Row,'InfoRow':Row})
  page=ns['AppsPage']();page.win=SimpleNamespace(on_page_filled=lambda _:None,apply=lambda *a,**kw:self.calls.append((a,kw)))
  group=SimpleNamespace(add=self.rows.append);page.build(SimpleNamespace(group=lambda:group));return page
 def test_missing_default_is_explicit_and_not_saved(self):
  page=self.page();row=next(r for r in self.rows if r.title=='Text editor')
  self.assertEqual(row.value,'');self.assertEqual(row.options[0],('','Not configured'));self.assertEqual(self.calls,[])
  row.on_change('');self.assertEqual(self.calls,[])
  row.on_change('viewer.desktop');self.assertEqual(self.calls[0][0],('xdg-mime','default','viewer.desktop','text/plain'))
 def test_existing_default_preserved_without_replacing(self):
  self.page('other.desktop');row=next(r for r in self.rows if r.title=='Text editor')
  self.assertEqual(row.value,'other.desktop');self.assertIn(('other.desktop','other'),row.options);self.assertEqual(self.calls,[])
 def test_failed_save_requeries_and_restores_actual_default(self):
  page=self.page('other.desktop');row=next(r for r in self.rows if r.title=='Text editor')
  row.value='viewer.desktop';row.on_change('viewer.desktop')
  self.calls[0][1]['done'](1,'failed write')
  self.assertEqual(row.value,'other.desktop')
  row.value='';row.on_change('');self.assertEqual(row.value,'other.desktop');self.assertEqual(len(self.calls),1)
 def test_no_handler_explains_missing_category(self):
  self.page(entries=[]);self.assertEqual(len(self.rows),9)
  self.assertTrue(all(r.sub=='No installed app supports this file type' for r in self.rows))
if __name__=='__main__':unittest.main()
