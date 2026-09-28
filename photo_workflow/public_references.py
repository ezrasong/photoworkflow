"""Explicit public-query/image retrieval; no access to selected private inputs."""
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
from urllib.parse import urlencode
import uuid

from PIL import Image

from .runtime import ROOT
MAX_BYTES = 20 * 1024**2

def fetch(url, domains, *, as_json=False):
    chain = []
    for _ in range(6):
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.port not in (None, 443) or
                parsed.username or parsed.password or parsed.hostname not in domains):
            raise ValueError('URL/redirect must use HTTPS on an explicitly allowed domain')
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)}
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise ValueError('Private, reserved and loopback addresses are forbidden')
        # Connect to the validated address directly, preserving hostname TLS verification.
        # This avoids a second DNS resolution and ignores ambient HTTP proxy settings.
        raw = socket.create_connection((sorted(addresses)[0], 443), timeout=30)
        conn = http.client.HTTPSConnection(parsed.hostname, timeout=30)
        try:
            conn.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=parsed.hostname)
            request_path = parsed.path or '/'
            if parsed.query:
                request_path += '?' + parsed.query
            conn.request('GET', request_path, headers={'User-Agent': 'LocalPhotoWorkflow/1.0', 'Accept': 'application/json' if as_json else 'image/jpeg,image/png'})
            response = conn.getresponse()
            chain.append(url)
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location:
                    raise ValueError('Redirect without Location')
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError('HTTP status ' + str(response.status))
            content_type = response.getheader('Content-Type', '').split(';')[0].lower()
            if content_type not in (('application/json',) if as_json else ('image/jpeg', 'image/png')):
                raise ValueError('Unexpected HTTP content type')
            if response.getheader('Content-Encoding', 'identity') != 'identity':
                raise ValueError('Encoded response bodies are unsupported')
            length = response.getheader('Content-Length')
            if length and int(length) > MAX_BYTES:
                raise ValueError('Download exceeds 20 MiB')
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError('Download exceeds 20 MiB')
            if as_json:
                return json.loads(data), chain
            image = Image.open(io.BytesIO(data))
            expected = 'JPEG' if content_type == 'image/jpeg' else 'PNG'
            if image.format != expected or image.width * image.height > 24_000_000 or getattr(image, 'n_frames', 1) != 1:
                raise ValueError('Invalid type, animation or oversized dimensions')
            image.verify()
            return data, expected.lower(), chain
        finally:
            conn.close()
            raw.close()
    raise ValueError('Too many redirects')


def search(query):
    """Only the caller's explicit public text query is sent to Commons."""
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 200 or any(ord(c)<32 for c in query):
        raise ValueError('Enter 1–200 printable characters for the public search')
    params = {'action':'query','format':'json','generator':'search','gsrsearch':query.strip()+' filetype:bitmap',
              'gsrnamespace':6,'gsrlimit':12,'prop':'imageinfo','iiprop':'url|extmetadata|mime|size','iiurlwidth':1600}
    data, chain = fetch('https://commons.wikimedia.org/w/api.php?'+urlencode(params), {'commons.wikimedia.org'}, as_json=True)
    if 'error' in data: raise RuntimeError('Reference provider error: '+str(data['error'].get('info','unknown')))
    result=[]
    def clean(value):
        import html
        return html.unescape(re.sub('<[^>]+>','',value or ''))[:1500]
    for item in sorted(data.get('query',{}).get('pages',{}).values(),key=lambda x:x.get('index',99)):
        infos=item.get('imageinfo',[])
        if not infos or infos[0].get('mime') not in {'image/jpeg','image/png'}:continue
        info=infos[0];metadata=info.get('extmetadata',{})
        result.append({'title':clean(item['title']), 'url':info.get('thumburl') or info['url'],
            'original_url':info['url'], 'source_page':info['descriptionurl'],
            'license':clean(metadata.get('LicenseShortName',{}).get('value')),
            'license_url':metadata.get('LicenseUrl',{}).get('value',''),
            'artist':clean(metadata.get('Artist',{}).get('value')),
            'credit':clean(metadata.get('Credit',{}).get('value'))})
    return result


def download(item, query):
    """Download a user-chosen Commons rendition; preserve attribution and hashes."""
    data, extension, chain = fetch(item['url'], {'upload.wikimedia.org','thumb.wikimedia.org'})
    digest=hashlib.sha256(data).hexdigest()
    folder=ROOT/'references/web'/uuid.uuid4().hex;folder.mkdir(parents=True)
    path=folder/('reference.'+extension);path.write_bytes(data)
    record=dict(item,query=query,file=path.name,sha256=digest,bytes=len(data),redirect_chain=chain,
                retrieved_utc=datetime.now(timezone.utc).isoformat(),use='User-selected visual reference; not restoration ground truth')
    from .runtime import json_write
    json_write(folder/'provenance.json',record)
    return path

