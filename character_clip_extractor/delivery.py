"""Unified large-file delivery for every artifact this project produces.

Policy (hard requirements):
  - Files are NEVER split into Telegram chunks.
  - Files > TG_MAX_BYTES are uploaded to storage.to (anonymous, multipart)
    and the download link is sent to Telegram as a normal message.
  - Files <= TG_MAX_BYTES go through Telegram sendDocument directly.
    Either way EVERY file travels through deliver_auto() — one code path.
  - The storage.to X-Visitor-Token is generated once, persisted on disk and
    reused for all subsequent uploads. It is never printed or sent.
  - Multipart uploads retry failed parts; unrecoverable uploads are aborted
    via /upload/abort and the error is reported.
  - After a storage.to confirm, the local file is deleted unless the caller
    asks to keep it.

Public API:
    deliver_auto(path, caption='', keep=False, chat=None) -> dict
    upload_storage_to(path) -> dict(url, filename, human_size, expires_at)
    send_document(path, caption='') -> bool
"""
import json
import mimetypes
import os
import secrets
import shutil
import time
import urllib.request
import urllib.error

import requests

STORAGE_API = os.environ.get('CCE_STORAGE_API', 'https://storage.to/api')
TG_TOKEN = os.environ.get('CCE_TG_TOKEN',
                          'REDACTED')
TG_CHAT = os.environ.get('CCE_TG_CHAT', 'REDACTED')
TG_MAX_BYTES = 50 * 1024 * 1024          # hard Bot API limit
SAFE_TG_BYTES = 49 * 1024 * 1024         # practical margin
TOKEN_FILE = os.environ.get(
    'CCE_VISITOR_TOKEN_FILE',
    os.path.expanduser('~/.cache/character_clip_extractor_visitor_token'))

PART_PUT_RETRIES = 3
PUT_TIMEOUT = (30, 3600)                 # slow uplinks, big parts


def log(msg):
    print(f'[delivery {time.strftime("%H:%M:%S")}] {msg}', flush=True)


# ---------------------------------------------------------------- token ---
def visitor_token():
    """Persistent random X-Visitor-Token: generate once, reuse forever."""
    if os.path.exists(TOKEN_FILE):
        tok = open(TOKEN_FILE).read().strip()
        if tok:
            return tok
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    tok = secrets.token_hex(32)
    with open(TOKEN_FILE, 'w') as f:
        f.write(tok)
    log('generated persistent storage.to visitor token')
    return tok


def _hdr():
    return {'X-Visitor-Token': visitor_token()}


# ---------------------------------------------------------- storage.to ---
def _abort(upload_id):
    try:
        requests.post(f'{STORAGE_API}/upload/abort',
                      json={'upload_id': upload_id}, headers=_hdr(), timeout=30)
        log(f'upload {upload_id} aborted')
    except Exception as e:
        log(f'abort failed: {e}')


def _put_with_retries(url, blob_or_path, offset=None, length=None,
                      extra_headers=None, tries=PART_PUT_RETRIES):
    """PUT bytes with retries; returns True on 2xx. (ETag handled by caller)"""
    headers = dict(extra_headers or {})
    for attempt in range(1, tries + 1):
        try:
            if isinstance(blob_or_path, bytes):
                data = blob_or_path
            else:
                with open(blob_or_path, 'rb') as f:
                    f.seek(offset or 0)
                    data = f.read(length)
            r = requests.put(url, data=data, headers=headers,
                             timeout=PUT_TIMEOUT)
            if r.status_code in (200, 201):
                return True, r.headers.get('ETag') or r.headers.get('etag')
            log(f'  PUT attempt {attempt}: status={r.status_code}')
        except Exception as e:
            log(f'  PUT attempt {attempt}: {e}')
        time.sleep(4 * attempt)
    return False, None


def upload_storage_to(path):
    """Upload a file to storage.to anonymously. Returns file info dict."""
    path = os.path.abspath(path)
    fname = os.path.basename(path)
    size = os.path.getsize(path)
    ctype = mimetypes.guess_type(fname)[0] or 'application/octet-stream'
    log(f'storage.to init: {fname} ({size} bytes, {ctype})')
    r = requests.post(f'{STORAGE_API}/upload/init',
                      json={'filename': fname, 'content_type': ctype,
                            'size': size},
                      headers=_hdr(), timeout=60)
    try:
        d = r.json()
    except Exception:
        raise RuntimeError(f'storage.to init non-JSON: {r.status_code} '
                           f'{r.text[:300]}')
    if r.status_code not in (200, 201) or not d.get('success', True):
        raise RuntimeError(f'storage.to init failed: {r.status_code} '
                           f'{r.text[:300]}')
    upload_id = d.get('upload_id') or d.get('uploadId')
    r2_key = d.get('r2_key') or d.get('r2Key') or ''
    put_headers = {}
    for k, v in (d.get('headers') or {}).items():
        if isinstance(v, list):
            v = v[0] if v else None
        if v:
            put_headers[k] = v

    if d.get('type') == 'single' or d.get('upload_url'):
        log('storage.to: single-part PUT')
        ok, _ = _put_with_retries(d['upload_url'], path,
                                  extra_headers=put_headers)
        if not ok:
            if upload_id:
                _abort(upload_id)
            raise RuntimeError('storage.to single PUT failed after retries')
    else:
        part_size = int(d.get('part_size') or d.get('partSize'))
        n_parts = (size + part_size - 1) // part_size
        log(f'storage.to: multipart, {n_parts} parts x {part_size}B')
        urls = {int(p['part_number']): p['url']
                for p in (d.get('parts') or [])}
        etags = {}

        def fetch_urls(pn, count):
            pr = requests.post(f'{STORAGE_API}/upload/parts',
                               json={'upload_id': upload_id,
                                     'part_number': pn, 'count': count},
                               headers=_hdr(), timeout=60)
            pj = pr.json() if pr.status_code in (200, 201) else {}
            for p in (pj.get('parts') or []):
                urls[int(p['part_number'])] = p['url']

        for pn in range(1, n_parts + 1):
            if pn not in urls:
                fetch_urls(pn, n_parts - pn + 1)
            if pn not in urls:
                _abort(upload_id)
                raise RuntimeError(f'no presigned URL for part {pn}')
            offset, length = (pn - 1) * part_size, min(part_size, size - offset)
            ok, etag = _put_with_retries(urls[pn], path, offset, length,
                                         extra_headers=put_headers)
            if not (ok and etag):
                fetch_urls(pn, 1)                     # fresh URL, last chance
                ok, etag = _put_with_retries(urls.get(pn, ''), path, offset,
                                             length, tries=2)
            if not (ok and etag):
                _abort(upload_id)
                raise RuntimeError(f'part {pn}/{n_parts} failed — aborted')
            etags[pn] = etag.strip('"')
            log(f'  part {pn}/{n_parts} OK')
        cr = requests.post(f'{STORAGE_API}/upload/complete-multipart',
                           json={'upload_id': upload_id,
                                 'parts': [{'partNumber': pn, 'etag': et}
                                           for pn, et in sorted(etags.items())]},
                           headers=_hdr(), timeout=120)
        if cr.status_code not in (200, 201):
            _abort(upload_id)
            raise RuntimeError(f'complete-multipart failed: {cr.status_code} '
                               f'{cr.text[:200]}')

    cf = requests.post(f'{STORAGE_API}/upload/confirm',
                       json={'filename': fname, 'size': size,
                             'content_type': ctype, 'r2_key': r2_key},
                       headers=_hdr(), timeout=120)
    try:
        cj = cf.json()
    except Exception:
        raise RuntimeError(f'confirm non-JSON: {cf.status_code} {cf.text[:300]}')
    finfo = cj.get('file') or cj
    res = {'url': finfo.get('url'), 'filename': finfo.get('filename', fname),
           'human_size': finfo.get('human_size') or f'{size/1e6:.1f} MB',
           'expires_at': finfo.get('expires_at'), 'size': size}
    log(f"storage.to OK: {res['url']}")
    return res


# ------------------------------------------------------------ telegram ---
def _tg(method, payload):
    r = requests.post(f'https://api.telegram.org/bot{TG_TOKEN}/{method}',
                      json=payload, timeout=120)
    ok = r.status_code == 200 and r.json().get('ok')
    if not ok:
        log(f'telegram {method} failed: {r.text[:200]}')
    return ok


def send_document(path, caption=''):
    """Direct Telegram sendDocument (only for small files)."""
    path = os.path.abspath(path)
    with open(path, 'rb') as f:
        r = requests.post(
            f'https://api.telegram.org/bot{TG_TOKEN}/sendDocument',
            data={'chat_id': TG_CHAT, 'caption': caption[:1000]},
            files={'document': (os.path.basename(path), f)}, timeout=600)
    ok = r.status_code == 200 and r.json().get('ok')
    log(f'telegram sendDocument {os.path.basename(path)}: '
        f'{"OK" if ok else "FAILED " + r.text[:200]}')
    return ok


# --------------------------------------------------------------- entry ---
def deliver_auto(path, caption='', keep=False, chat=None):
    """THE single delivery path for every artifact.

    <= SAFE_TG_BYTES -> sendDocument. Larger -> storage.to + message with
    clickable download link, size and expiry. Local file is deleted after a
    successful storage.to confirm unless keep=True.
    Returns dict(kind, ok, ...).
    """
    global TG_CHAT
    if chat:
        TG_CHAT = chat
    path = os.path.abspath(path)
    if not os.path.exists(path):
        return {'kind': 'none', 'ok': False, 'error': 'file not found'}
    size = os.path.getsize(path)
    if size <= SAFE_TG_BYTES:
        ok = send_document(path, caption)
        return {'kind': 'telegram', 'ok': ok, 'path': path}
    res = upload_storage_to(path)
    expires = res.get('expires_at') or 'n/a'
    cap = f'\n\n{caption}' if caption else ''
    msg = (f"📁 <b>{res['filename']}</b>\n"
           f"💾 Size: {res['human_size']}\n"
           f"⏳ Available until: {expires}\n"
           f"⬇️ Download: {res['url']}{cap}")
    tg_ok = _tg('sendMessage', {'chat_id': TG_CHAT, 'text': msg,
                                'disable_web_page_preview': False})
    if not keep:
        os.remove(path)
        log(f'local file removed after confirm: {path}')
    return {'kind': 'storage.to', 'ok': tg_ok, **res}
