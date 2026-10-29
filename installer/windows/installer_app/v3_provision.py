"""Provision an isolated V3 machine identity for the Windows signing client.

This exchange uses a random machine identifier and no Apple account/password.
The file format and protocol follow SideSign 0.1.7 and its pinned AnisetteKit:
https://github.com/SideStore/SideSign/blob/10b446fc6fc47fe81b60879dfb126d0c8098ec29/CLI/DeviceDataManager.swift
https://github.com/mahee96/AnisetteKit/blob/1f5a7e36553cc865b873f222b87a6486c0bcc7bf/Sources/AnisetteClient.swift

No Apple account or password participates in this device provisioning exchange.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import secrets
import ssl
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from websockets.sync.client import connect

from .paths import ASSETS
HERE = ASSETS
APPLE_LOOKUP = 'https://gsa.apple.com/grandslam/GsService2/lookup'
SERVER = 'https://new.ani.sidestore.io'
SOCKET = 'wss://new.ani.sidestore.io/v3/provisioning_session'
TIMEOUT = 20


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def apple_url(value):
    url = urlsplit(value)
    if url.scheme != 'https' or url.hostname != 'gsa.apple.com' or url.port not in (None, 443):
        raise ValueError('unexpected_apple_provisioning_endpoint')
    return value


def provision(*, protocol_v3=True, client_info=None, user_agent=None, server=SERVER):
    identifier = uuid.uuid4()
    context = ssl.create_default_context(cafile=str(HERE / 'apple_trust_bundle.pem'))
    opener = build_opener(NoRedirect, HTTPSHandler(context=context))
    routing = '17106176'

    def request(url, data=None):
        headers = {
            'User-Agent': user_agent or 'AuthKit/1 (Macintosh; OS X 26.6) (com.apple.akd/1.0)',
            'X-Mme-Client-Info': client_info or '<MacBookPro18,3> <macOS;26.6;25F84> <com.apple.AuthKit/1 (com.apple.akd/1.0)>',
            'X-Mme-Device-Id': str(identifier) if protocol_v3 else str(identifier).upper(),
            'X-Apple-I-MD-LU': hashlib.sha256(identifier.bytes).hexdigest() if protocol_v3 else '0' * 63 + '1',
            'X-Apple-I-MD-RINFO': routing,
            'X-Apple-I-SRL-NO': '0',
            'X-Apple-I-Client-Time': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'X-Apple-Locale': 'en_US',
            'X-Apple-I-TimeZone': 'UTC',
            'Content-Type': 'text/x-xml-plist',
            'Accept': '*/*',
        }
        with opener.open(Request(apple_url(url), data=data, headers=headers), timeout=TIMEOUT) as response:
            content = response.read(1024 * 1024 + 1)
            if len(content) > 1024 * 1024:
                raise ValueError('apple_response_too_large')
            return plistlib.loads(content), response.headers.get('X-Apple-I-MD-RINFO')

    lookup, route = request(APPLE_LOOKUP)
    if route:
        routing = route
    start = apple_url(lookup['urls']['midStartProvisioning'])
    finish = apple_url(lookup['urls']['midFinishProvisioning'])
    data, route = request(start, plistlib.dumps({'Header': {}, 'Request': {}}))
    if route:
        routing = route
    routing = str(data.get('Response', {}).get('routing-info', routing))
    spim = data['Response']['spim']
    if server not in ('https://ani.sidestore.io', 'https://new.ani.sidestore.io'):
        raise ValueError('unexpected_anisette_server')
    socket_url = server.replace('https://', 'wss://', 1) + '/v3/provisioning_session'
    with connect(socket_url, ssl=context, open_timeout=TIMEOUT, close_timeout=3, max_size=1024 * 1024) as ws:
        step = json.loads(ws.recv(timeout=TIMEOUT))
        if step.get('result') != 'GiveIdentifier':
            raise ValueError('unexpected_anisette_step_identifier')
        encoded_id = base64.b64encode(identifier.bytes).decode() if protocol_v3 else identifier.bytes.hex()
        ws.send(json.dumps({'identifier': encoded_id}))
        step = json.loads(ws.recv(timeout=TIMEOUT))
        if step.get('result') != 'GiveStartProvisioningData':
            raise ValueError('unexpected_anisette_step_start')
        ws.send(json.dumps({'spim': spim}))
        step = json.loads(ws.recv(timeout=TIMEOUT))
        if step.get('result') != 'GiveEndProvisioningData':
            raise ValueError('unexpected_anisette_step_end')
        data, route = request(finish, plistlib.dumps({'Header': {}, 'Request': {'cpim': step['cpim']}}))
        response = data['Response']
        routing = str(response.get('routing-info', route or routing))
        ws.send(json.dumps({'ptm': response['ptm'], 'tk': response['tk']}))
        step = json.loads(ws.recv(timeout=TIMEOUT))
        if step.get('result') != 'ProvisioningSuccess':
            raise ValueError('unexpected_anisette_step_finish')
        adi = base64.b64decode(step['adi_pb'], validate=True)
        if not adi:
            raise ValueError('empty_machine_data')
    return identifier, adi, routing


def write_machine(path, password, identifier, adi):
    # Compatible with SideSign v0.1.7 DeviceDataManager: ADI1, salt, nonce,
    # tag, and ciphertext. No plaintext machine state is written to disk.
    data = plistlib.dumps({'identifier': str(identifier).upper(), 'adiBlob': adi}, fmt=plistlib.FMT_BINARY)
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100_000, dklen=32)
    sealed = AESGCM(key).encrypt(nonce, data, None)
    path.write_bytes(b'ADI1' + salt + nonce + sealed[-16:] + sealed[:-16])

