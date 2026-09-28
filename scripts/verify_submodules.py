"""Keep upstream source references aligned with shipped release manifests.

Uses Git's index, so CI does not need to fetch or execute upstream source.
"""
import configparser
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def verify(pins, modules, gitlinks):
    expected = {}
    for pin in pins:
        if 'repository' not in pin:
            continue
        repository = pin['repository']
        if repository in expected or not re.fullmatch(r'[0-9a-f]{40}', pin.get('commit', '')):
            raise ValueError(f'Invalid or duplicate source pin: {repository}')
        expected[repository] = pin['commit']
    actual = {}
    for section in modules.sections():
        path = modules[section]['path']
        url = modules[section]['url']
        match = re.fullmatch(r'https://github\.com/([^/]+/[^/]+)\.git', url)
        if not match or match[1] in actual:
            raise ValueError(f'Invalid or duplicate submodule repository: {url}')
        if path not in gitlinks:
            raise ValueError(f'Missing Git submodule entry: {path}')
        actual[match[1]] = gitlinks[path]
    if actual.keys() != expected.keys():
        raise ValueError('Every submodule must have a repository/commit pin in a packaging manifest')
    for repository, commit in expected.items():
        if actual[repository] != commit:
            raise ValueError(
                f'{repository}: submodule {actual[repository]} differs from bundled source {commit}. '
                'Review the upstream release and update its version, downloads, hashes, source commit '
                'and notices together before merging. A source-only bump does not upgrade the app.')


def main():
    modules = configparser.ConfigParser(interpolation=None)
    modules.read(ROOT / '.gitmodules', encoding='utf-8')
    staged = subprocess.check_output(
        ['git', 'ls-files', '--stage', '-z'], cwd=ROOT, text=True)
    gitlinks = {}
    for record in staged.split('\0'):
        if not record:
            continue
        metadata, path = record.split('\t', 1)
        mode, commit, stage = metadata.split()
        if mode == '160000' and stage == '0':
            gitlinks[path] = commit
    pins = list(json.loads((ROOT / 'packaging/creative-mcp.json').read_text(encoding='utf-8')).values())
    pins += list(json.loads((ROOT / 'packaging/downloads.json').read_text(encoding='utf-8'))['files'].values())
    verify(pins, modules, gitlinks)
    print(f'All {len(modules.sections())} submodule pins match the bundled releases.')


if __name__ == '__main__':
    main()
