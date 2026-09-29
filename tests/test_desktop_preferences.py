"""Desktop preferences use the existing atomic JSON store and retain old fields."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from photo_workflow import desktop


class DesktopPreferencesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'desktop').mkdir()
        self.patch = patch.object(desktop, 'ROOT', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.app = desktop.Desktop.__new__(desktop.Desktop)
        self.app.guard = threading.Lock()

    def settings(self, **args):
        return self.app.dispatch('settings', args)

    def test_legacy_preferences_merge_and_restart(self):
        self.settings(value={'theme': 'light', 'reviewZoom': '100%'})
        tabs = {'order': ['review', 'controls', 'prompts', 'browser'], 'hidden': ['browser'], 'active': 'review'}
        self.settings(value={'detailTabs': tabs})
        self.assertEqual(self.settings(), {'theme': 'light', 'reviewZoom': '100%', 'detailTabs': tabs})
        self.settings(value={'theme': 'dark'})
        disk = json.loads((self.root / 'desktop/settings.json').read_text())
        self.assertEqual(disk['detailTabs'], tabs)
        self.assertEqual(disk['reviewZoom'], '100%')

    def test_all_closed_is_valid_and_invalid_values_do_not_write(self):
        closed = {'order': ['controls', 'review', 'prompts', 'browser'], 'hidden': ['controls', 'review', 'prompts', 'browser'], 'active': None}
        good = self.settings(value={'detailTabs': closed})
        for patch_value in [
            {'order': ['controls', 'controls', 'prompts', 'browser']}, {'order': ['controls']},
            {'hidden': ['unknown']}, {'hidden': ['controls', 'controls']},
            {'active': 'browser'}, {'active': []}, {'order': [[], 'review', 'prompts', 'browser']},
            {'hidden': []}, {'extra': True},
        ]:
            with self.subTest(patch_value=patch_value), self.assertRaises(ValueError):
                self.settings(value={'detailTabs': {**closed, **patch_value}})
            self.assertEqual(self.settings(), good)

    def test_removed_navigation_preferences_are_retired_without_losing_settings(self):
        path = self.root / 'desktop/settings.json'
        path.write_text(json.dumps({'theme': 'light', 'reviewZoom': '100%', 'sidebarTabs': {'active': None}}))
        saved = self.settings(value={'detailTabs': {'order': ['controls', 'review', 'prompts', 'browser'], 'hidden': [], 'active': 'controls'}})
        self.assertNotIn('sidebarTabs', saved)
        self.assertEqual(saved['theme'], 'light')
        self.assertEqual(saved['reviewZoom'], '100%')

    def test_parallel_partial_writes_do_not_lose_fields(self):
        import concurrent.futures
        tabs = {'order': ['controls', 'review', 'prompts', 'browser'], 'hidden': [], 'active': 'controls'}
        with concurrent.futures.ThreadPoolExecutor() as pool:
            list(pool.map(lambda value: self.settings(value=value), [{'theme': 'light'}, {'reviewZoom': '100%'}, {'detailTabs': tabs}]))
        self.assertEqual(self.settings(), {'theme': 'light', 'reviewZoom': '100%', 'detailTabs': tabs})


if __name__ == '__main__':
    unittest.main()
