#!/usr/bin/env python3
"""Source the actual rendered desktop environment under strict POSIX sh."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
CONF=ROOT/'integration/carpatic/configurator'


class RenderedProfile(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.home=Path(self.tmp.name)
        self.config=self.home/'.config/carpatic'
        self.config.mkdir(parents=True)
        self.kvantum=self.home/'system-Kvantum'
        r=subprocess.run(['sh',str(CONF/'bin/carpatic-render'),str(CONF/'themes/carpatic/colors.toml'),str(CONF/'templates/apps/env.sh.tpl'),'THEME=carpatic'],capture_output=True,text=True,check=True)
        # Redirect only absolute optional system directory to the owned fixture.
        self.assertEqual(r.stdout.count('/usr/share/Kvantum'),1)
        self.rendered=r.stdout.replace('/usr/share/Kvantum',str(self.kvantum))
        self.profile=self.home/'env.sh'
        self.profile.write_text(self.rendered)

    def tearDown(self):self.tmp.cleanup()

    def source(self,text=None):
        if text is not None:self.profile.write_text(text)
        env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'HOME':str(self.home),'STARSHIP_CONFIG':'preserved-starship','QT_STYLE_OVERRIDE':'preserved-qt'}
        cmd='. "$1"; printf "%s\\n" REACHED "$CLICOLOR" "$BAT_THEME" "$FOREGROUND" "$STARSHIP_CONFIG" "$QT_STYLE_OVERRIDE"'
        return subprocess.run(['sh','-e','-c',cmd,'fixture',str(self.profile)],env=env,text=True,capture_output=True)

    def test_missing_optional_dependencies_do_not_abort(self):
        r=self.source()
        self.assertEqual(r.returncode,0,r.stderr)
        lines=r.stdout.splitlines()
        self.assertEqual(lines[:3],['REACHED','1','carpatic'])
        self.assertRegex(lines[3],r'^#[0-9a-fA-F]{6}$')
        self.assertEqual(lines[-2:],['preserved-starship','preserved-qt'])

    def test_present_optional_paths_export_values(self):
        (self.config/'starship.toml').write_text('# test configuration\n')
        self.kvantum.mkdir()
        r=self.source()
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(r.stdout.splitlines()[-2:],[str(self.config/'starship.toml'),'kvantum'])

    def test_user_starship_configuration_is_preserved(self):
        (self.config/'starship.toml').write_text('# generated\n')
        (self.home/'.config/starship.toml').write_text('# user\n')
        r=self.source()
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(r.stdout.splitlines()[-2],'preserved-starship')

    def test_old_missing_optional_expression_reproduces_exit(self):
        r=self.source(self.rendered+'\n[ -d "'+str(self.kvantum)+'" ] && export QT_STYLE_OVERRIDE=kvantum\n')
        self.assertNotEqual(r.returncode,0)
        self.assertNotIn('REACHED',r.stdout)

    def test_real_syntax_errors_still_abort(self):
        r=self.source(self.rendered+'\nif\n')
        self.assertNotEqual(r.returncode,0)
        self.assertNotIn('REACHED',r.stdout)


if __name__=='__main__':unittest.main()
