"""Real offline MCP startup checks; no host mutations, GPU or models required."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT/'.cache/packaging/bundle'


def main():
    results = []
    with tempfile.TemporaryDirectory(prefix='Photo Studio MCP ') as temp:
        env = dict(os.environ, PHOTOWORKFLOW_HOME=temp)
        env['PATH'] = str(Path(os.environ['SYSTEMROOT'])/'System32')
        for name, count in [('photoshop', 125), ('lightroom', 18), ('resolve', 37)]:
            result = subprocess.run([str(BUNDLE/'python/python.exe'), '-I',
                                     str(BUNDLE/'integrations/creative-mcp.py'), 'probe', name],
                                    env=env, capture_output=True, text=True, encoding='utf-8',
                                    timeout=55, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode: raise RuntimeError(result.stderr[-3000:])
            data = json.loads(result.stdout)
            assert data['serverReady'] and not data['hostChecked'], data
            assert data['toolCount'] == count, data
            results.append(data)
    report = ROOT/'.cache/creative-mcp-verification.json'
    report.write_text(json.dumps({'status': 'passed', 'servers': results}, indent=2)+'\n')
    print(report)


if __name__ == '__main__': main()
