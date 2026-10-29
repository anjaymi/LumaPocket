"""Download pinned official portable tools without installing them system-wide."""
import hashlib
import ctypes
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import ssl
import stat
import subprocess
import urllib.request
import zipfile

from .paths import ASSETS, data_dir

FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
TOOLS = {
    'gh': ('https://github.com/cli/cli/releases/download/v2.103.3/gh_2.103.3_windows_amd64.zip',
           '98d0cfa794721665d7973dd728c78aff7bd836d58f10f6d7a03568eccb0a22e0', 40 * 1024 * 1024),
    'git': ('https://github.com/git-for-windows/git/releases/download/v2.56.0.windows.4/PortableGit-2.56.0.4-64-bit.7z.exe',
            'b1f3e52216e2ed6882d1bebfd4d3fdf319bec40d2edbbf9fd26ec4fd3fce7ed1', 100 * 1024 * 1024),
}
APPLE_CA = 'b0b1730ecbc7ff4505142c49f1295e6eda6bcaed7e2c68c5be91b5a11001f024'


def download_checked(name, emit):
    url, digest, limit = TOOLS[name]
    cache = data_dir() / 'cache'
    cache.mkdir(exist_ok=True)
    target = cache / ('gh.zip' if name == 'gh' else 'PortableGit.7z.exe')
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
        return target
    pending = target.with_suffix('.partial')
    request = urllib.request.Request(url, headers={'User-Agent': 'LumaPocket-Installer/0.1'})
    try:
        with urllib.request.urlopen(request, timeout=45) as response, pending.open('wb') as stream:
            total, last = 0, -1
            size = int(response.headers.get('Content-Length', 0))
            hasher = hashlib.sha256()
            while chunk := response.read(256 * 1024):
                total += len(chunk)
                if total > limit:
                    raise ValueError('tool_download_too_large')
                stream.write(chunk)
                hasher.update(chunk)
                percent = int(total * 100 / size) if size else 0
                if percent != last:
                    emit('download_progress', {'tool': name, 'percent': min(percent, 100)})
                    last = percent
        if hasher.hexdigest() != digest:
            raise ValueError('tool_download_checksum_mismatch')
        pending.replace(target)
        return target
    finally:
        pending.unlink(missing_ok=True)


def extract_zip(archive, target):
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        total = 0
        for item in source.infolist():
            path = PurePosixPath(item.filename)
            total += item.file_size
            if (path.is_absolute() or '..' in path.parts or '\\' in item.filename or ':' in item.filename or
                    stat.S_ISLNK(item.external_attr >> 16) or total > 256 * 1024 * 1024):
                raise ValueError('unsafe_tool_archive')
            dest = target / path.as_posix()
            if item.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with source.open(item) as inp, dest.open('wb') as out:
                    shutil.copyfileobj(inp, out)


def ensure_tools(emit):
    tools = data_dir() / 'tools'
    tools.mkdir(exist_ok=True)
    gh = tools / 'gh' / 'bin' / 'gh.exe'
    if not gh.is_file():
        emit('status', '正在准备 GitHub 登录组件…')
        archive = download_checked('gh', emit)
        extract_zip(archive, tools / 'gh')
    git = tools / 'git'
    if not all((git / 'usr' / 'bin' / n).is_file() for n in ('gpg.exe', 'gpgconf.exe', 'openssl.exe')):
        emit('status', '正在准备便携签名组件，首次使用需要下载…')
        archive = download_checked('git', emit)
        git.mkdir(exist_ok=True)
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        result = subprocess.run([str(archive), '-y', '-o' + str(git)], cwd=git,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=180, creationflags=FLAGS, startupinfo=startup)
        if result.returncode:
            raise ValueError('portable_tool_extraction_failed')
    if not gh.is_file() or not all((git / 'usr' / 'bin' / n).is_file() for n in ('gpg.exe', 'gpgconf.exe', 'openssl.exe')):
        raise ValueError('portable_tools_missing')
    return gh


def check_cpp_runtime():
    try:
        for name in ('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll'):
            ctypes.WinDLL(name)
    except OSError:
        raise ValueError('windows_cpp_runtime_required') from None


def apple_root_trusted():
    try:
        return any(hashlib.sha256(cert).hexdigest() == APPLE_CA
                   for cert, encoding, trust in ssl.enum_certificates('ROOT') if encoding == 'x509_asn')
    except (AttributeError, OSError):
        return False


def install_apple_root():
    path = ASSETS / 'AppleIncRootCertificate.cer'
    if hashlib.sha256(path.read_bytes()).hexdigest() != APPLE_CA:
        raise ValueError('apple_certificate_checksum_mismatch')
    if apple_root_trusted():
        return
    certutil = Path(os.environ.get('SYSTEMROOT', r'C:\Windows')) / 'System32' / 'certutil.exe'
    result = subprocess.run([str(certutil), '-user', '-addstore', 'Root', str(path)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, creationflags=FLAGS)
    if result.returncode or not apple_root_trusted():
        raise ValueError('apple_certificate_install_failed')
    (data_dir() / 'apple-root-receipt.json').write_text(json.dumps({
        'thumbprintSha256': APPLE_CA, 'store': 'CurrentUser/Root', 'userApproved': True,
    }), encoding='utf-8')
