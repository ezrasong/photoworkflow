"""Optional installation-like retrieval. Never imported by the processing pipeline.

Use explicit public URLs, subject, query and allowed domains. No search service,
local photos or person notes are read. JSON is configuration, not a sandbox.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import io
import ipaddress
import json
from pathlib import Path
import re
import socket
import ssl
from urllib.parse import urljoin, urlsplit
import uuid

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 20 * 1024**2

import sys
sys.path.insert(0, str(ROOT))
from photo_workflow.public_references import fetch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding='utf-8-sig'))
    if cfg.get('enabled') is not True or not cfg.get('subject') or not cfg.get('query'):
        raise ValueError('Explicit enabled=true, subject and public query are required')
    domains = cfg.get('domains', [])
    urls = cfg.get('urls', [])
    if not domains or not urls or len(urls) > 20:
        raise ValueError('Configure allowed domains and 1-20 explicit public image URLs')
    subject = re.sub(r'[^A-Za-z0-9_-]', '_', cfg['subject'])[:60]
    destination = ROOT / 'references' / 'web' / (subject + '-' + uuid.uuid4().hex[:12])
    destination.mkdir(parents=True)
    entries = []
    try:
        for url in urls:
            data, extension, chain = fetch(url, set(domains))
            digest = hashlib.sha256(data).hexdigest()
            name = digest + '.' + extension
            temporary = destination / (name + '.partial')
            temporary.write_bytes(data)
            temporary.replace(destination / name)
            entries.append({'file': name, 'sha256': digest, 'bytes': len(data), 'redirect_chain': chain,
                            'retrieved_utc': datetime.now(timezone.utc).isoformat(),
                            'license': 'Not inferred; verify rights at source before reuse'})
    finally:
        record = {'subject': cfg['subject'], 'query': cfg['query'], 'domains': domains, 'downloads': entries}
        temporary = destination / 'provenance.partial.json'
        temporary.write_text(json.dumps(record, indent=2), encoding='utf-8')
        temporary.replace(destination / 'provenance.json')
    print(destination)

if __name__ == '__main__':
    main()
