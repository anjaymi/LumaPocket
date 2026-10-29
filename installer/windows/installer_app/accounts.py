"""Keep this installer's GitHub login separate from system GitHub CLI accounts."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request

from .paths import data_dir, private_environment
from .tooling import FLAGS


def account_info():
    try:
        info = json.loads((data_dir() / 'active-account.json').read_text(encoding='utf-8'))
        if type(info['id']) is int and re.fullmatch(r'[A-Za-z0-9-]+', info['login']):
            return info
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def load_account():
    from lumapocket_signing.local_key import dpapi
    info = account_info()
    if not info:
        raise ValueError('github_login_required')
    path = data_dir() / 'accounts' / (str(info['id']) + '.dpapi')
    try:
        value = json.loads(dpapi(path.read_bytes(), decrypt=True))
        if value['id'] != info['id'] or value['login'] != info['login'] or len(value['token']) < 20:
            raise ValueError('invalid_account')
    except Exception:
        raise ValueError('github_login_required') from None
    return value


def save_account(value):
    from lumapocket_signing.local_key import dpapi
    target = data_dir() / 'accounts'
    target.mkdir(exist_ok=True)
    encrypted = dpapi(json.dumps(value).encode())
    pending = target / (str(value['id']) + '.pending')
    pending.write_bytes(encrypted)
    pending.replace(target / (str(value['id']) + '.dpapi'))
    active = data_dir() / 'active-account.pending'
    active.write_text(json.dumps({'id': value['id'], 'login': value['login']}), encoding='utf-8')
    active.replace(data_dir() / 'active-account.json')


def clean_login_temporary():
    base = (data_dir() / 'auth-volatile').resolve()
    if base.is_dir():
        for item in base.iterdir():
            # Only this application's randomly named login directories may be removed.
            if item.name.startswith('login-') and item.is_dir() and not item.is_symlink() and item.resolve().is_relative_to(base):
                shutil.rmtree(item)


def login(gh, emit):
    base = data_dir() / 'auth-volatile'
    base.mkdir(exist_ok=True)
    clean_login_temporary()
    with tempfile.TemporaryDirectory(prefix='login-', dir=base) as directory:
        env = private_environment()
        env['GH_CONFIG_DIR'] = directory
        command = [str(gh), 'auth', 'login', '--hostname', 'github.com', '--web',
                   '--git-protocol', 'https', '--scopes', 'repo,workflow', '--insecure-storage']
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, env=env, creationflags=FLAGS, bufsize=0)
        buffer, announced = '', False
        try:
            while True:
                chunk = os.read(process.stdout.fileno(), 1024)
                if not chunk:
                    break
                buffer = (buffer + chunk.decode('utf-8', errors='replace'))[-8192:]
                match = re.search(r'(?:one-time code|device code):\s*([A-Z0-9]{4}-[A-Z0-9]{4})', buffer, re.I)
                if match and not announced:
                    emit('github_code', match.group(1).upper())
                    process.stdin.write(b'\n')
                    process.stdin.flush()
                    announced = True
            if process.wait(timeout=15):
                raise ValueError('github_login_failed')
        finally:
            process.stdin.close()
            process.stdout.close()
            if process.poll() is None:
                process.terminate()
        token_result = subprocess.run([str(gh), 'auth', 'token', '--hostname', 'github.com'],
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                      env=env, timeout=20, creationflags=FLAGS)
        if token_result.returncode:
            raise ValueError('github_login_failed')
        token = token_result.stdout.decode().strip()
        request = urllib.request.Request('https://api.github.com/user',
            headers={'Authorization': 'Bearer ' + token, 'User-Agent': 'LumaPocket-Installer'})
        with urllib.request.urlopen(request, timeout=20) as response:
            user = json.load(response)
        if user.get('type') != 'User' or type(user.get('id')) is not int:
            raise ValueError('personal_github_account_required')
        save_account({'token': token, 'id': user['id'], 'login': user['login']})
        emit('github_ready', {'id': user['id'], 'login': user['login']})
