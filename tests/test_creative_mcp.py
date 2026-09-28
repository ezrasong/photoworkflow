import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from photo_workflow import creative_mcp

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO/'packaging'))
from build_creative_mcp import extract


class CreativeMcpTests(unittest.TestCase):
    def test_archive_rejects_all_entries_before_writing(self):
        for name in ('../escape', '/absolute', 'C:/escape', 'x:stream', 'ok/../../escape', '..\\escape'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                archive = Path(temp)/'input.zip'
                with zipfile.ZipFile(archive, 'w') as z:
                    z.writestr('good.txt', 'safe');z.writestr(name, 'unsafe')
                target = Path(temp)/'output'
                with self.assertRaises(ValueError): extract(archive, target)
                self.assertFalse(target.exists())

    def test_archive_rejects_links_and_extracts_regular_plugin(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp)/'input.zip'
            link = zipfile.ZipInfo('link');link.external_attr = 0o120777 << 16
            with zipfile.ZipFile(archive, 'w') as z: z.writestr(link, '../outside')
            with self.assertRaises(ValueError): extract(archive, Path(temp)/'out')
            with zipfile.ZipFile(archive, 'w') as z: z.writestr('root/plugin/Info.lua', 'plugin')
            extract(archive, Path(temp)/'out', 'root/')
            self.assertEqual((Path(temp)/'out/plugin/Info.lua').read_text(), 'plugin')

    def test_profile_is_relocated_without_touching_client_configs(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)/'user data';code = Path(temp)/'new install'
            sentinel = Path(temp)/'claude_desktop_config.json';sentinel.write_text('unchanged')
            with patch.object(creative_mcp, 'ROOT', home), patch.object(creative_mcp, 'CODE_ROOT', code):
                config = json.loads(Path(creative_mcp.write_config()).read_text())
            for name, server in config['mcpServers'].items():
                self.assertEqual(server['args'], ['-I', str(code/'integrations/creative-mcp.py'), 'serve', name])
                self.assertEqual(server['env']['PHOTOWORKFLOW_HOME'], str(home))
            self.assertEqual(sentinel.read_text(), 'unchanged')

    def test_child_environment_excludes_credentials_and_hooks(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {
            'PHOTOWORKFLOW_HOME': temp, 'OPENAI_API_KEY': 'test-secret', 'NODE_OPTIONS': '--eval=bad',
            'PYTHONPATH': 'untrusted', 'HTTP_PROXY': 'http://external.invalid'}):
            spec = importlib.util.spec_from_file_location('creative_launcher', REPO/'integrations/creative-mcp.py')
            module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            for name in creative_mcp.NAMES:
                env, state = module.environment(name)
                self.assertFalse({'OPENAI_API_KEY', 'NODE_OPTIONS', 'PYTHONPATH', 'HTTP_PROXY'} & env.keys())
                self.assertEqual(env['ANALYTICS_DISABLED'], '1')
                self.assertEqual(env['DAVINCI_RESOLVE_MCP_UPDATE_CHECK'], '0')
                self.assertTrue(state.is_relative_to(Path(temp).resolve()))

    def test_unknown_server_and_pre_cancel_never_spawn(self):
        with patch.object(creative_mcp.subprocess, 'Popen') as spawn:
            with self.assertRaises(ValueError): creative_mcp.inspect('shell')
            with patch.object(creative_mcp, 'inventory', return_value=[dict(id='resolve', bundled=True)]):
                with tempfile.TemporaryDirectory() as temp:
                    cancel = Path(temp)/'cancel';cancel.touch()
                    with self.assertRaisesRegex(RuntimeError, 'Cancelled'): creative_mcp.inspect('resolve', cancel_file=cancel)
            spawn.assert_not_called()

    def test_cancel_stops_running_inspection(self):
        with tempfile.TemporaryDirectory() as temp:
            code = Path(temp);(code/'integrations').mkdir()
            (code/'integrations/creative-mcp.py').write_text('import time\ntime.sleep(120)\n')
            cancel = code/'cancel';timer = threading.Timer(.5, cancel.touch)
            with patch.object(creative_mcp, 'CODE_ROOT', code), patch.object(creative_mcp, 'ROOT', code), \
                 patch.object(creative_mcp, 'inventory', return_value=[dict(id='resolve', bundled=True)]):
                timer.start()
                try:
                    with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                        creative_mcp.inspect('resolve', cancel_file=cancel)
                finally: timer.join()


if __name__ == '__main__': unittest.main()
