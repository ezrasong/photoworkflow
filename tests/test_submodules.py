import configparser
import unittest

from scripts.verify_submodules import verify


class SubmoduleTests(unittest.TestCase):
    def setUp(self):
        self.commit = 'a' * 40
        self.pins = [{'repository': 'owner/repo', 'commit': self.commit}]
        self.modules = configparser.ConfigParser(interpolation=None)
        self.modules.read_dict({'submodule "vendor/repo"': {
            'path': 'vendor/repo', 'url': 'https://github.com/owner/repo.git'}})
        self.gitlinks = {'vendor/repo': self.commit}

    def test_matching_pins_need_no_upstream_checkout(self):
        verify(self.pins + [{'url': 'https://example.com/runtime'}], self.modules, self.gitlinks)

    def test_source_only_update_is_blocked(self):
        self.gitlinks['vendor/repo'] = 'b' * 40
        with self.assertRaisesRegex(ValueError, 'source-only bump'):
            verify(self.pins, self.modules, self.gitlinks)

    def test_missing_gitlink_or_packaging_pin_is_blocked(self):
        with self.assertRaisesRegex(ValueError, 'Missing Git submodule'):
            verify(self.pins, self.modules, {})
        with self.assertRaisesRegex(ValueError, 'Every submodule'):
            verify([], self.modules, self.gitlinks)

    def test_changed_remote_and_duplicate_pin_are_blocked(self):
        self.modules['submodule "vendor/repo"']['url'] = 'https://github.com/other/repo.git'
        with self.assertRaisesRegex(ValueError, 'Every submodule'):
            verify(self.pins, self.modules, self.gitlinks)
        with self.assertRaisesRegex(ValueError, 'Invalid or duplicate'):
            verify(self.pins * 2, self.modules, self.gitlinks)


if __name__ == '__main__':
    unittest.main()
