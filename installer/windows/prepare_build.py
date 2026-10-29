"""Stage explicit public sources/assets; never copy any local signing state."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def prepare(target, authorization_assets):
    target.mkdir(parents=True, exist_ok=True)
    signing = target / 'lumapocket_signing'
    signing.mkdir(exist_ok=True)
    signing.joinpath('__init__.py').write_text('', encoding='utf-8')
    files = [p for p in (ROOT / 'signing').glob('*.py')
             if not p.name.startswith(('test_', 'check')) and p.name != 'ci_renew.py']
    modules = {p.stem for p in files}
    for source in files:
        text = source.read_text(encoding='utf-8')
        text = re.sub(r'^(\s*)from (\w+) import ',
                      lambda m: m.group(1) + 'from ' + ('lumapocket_signing.' if m.group(2) in modules else '') + m.group(2) + ' import ',
                      text, flags=re.MULTILINE)
        text = text.replace("patch('v3_guard.", "patch('lumapocket_signing.v3_guard.")
        ast.parse(text)
        (signing / source.name).write_text(text, encoding='utf-8')
    app = target / 'installer_app'
    shutil.copytree(HERE / 'installer_app', app, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__'))
    assets = app / 'assets'
    assets.mkdir(exist_ok=True)
    sources = {
        'sidesign.exe': authorization_assets / 'signer-recovery-40866853470' / 'windows' / 'sidesign.exe',
        'windows-runtime.zip': ROOT / 'signing' / 'windows-runtime.zip',
        'toolchain.json': ROOT / 'signing' / 'toolchain.json',
        'AppleIncRootCertificate.cer': authorization_assets / 'AppleIncRootCertificate.cer',
        'apple_trust_bundle.pem': authorization_assets / 'apple_trust_bundle.pem',
    }
    expected = set(sources) | {'signing-fingerprints.json', 'source.zip', 'NOTICES.txt', 'app_icon.ico'}
    if any(path.name not in expected or path.is_symlink() or not path.is_file() for path in assets.iterdir()):
        raise ValueError('Unexpected file in build assets; use a fresh staging directory')
    for name, source in sources.items():
        shutil.copyfile(source, assets / name)
    fingerprints = {name: hashlib.sha256((ROOT / 'signing' / name).read_bytes()).hexdigest()
                    for name in ('apple.py', 'v3_guard.py', 'certificate_recovery.py')}
    (assets / 'signing-fingerprints.json').write_text(json.dumps(fingerprints, indent=2), encoding='utf-8')
    shutil.copyfile(HERE / 'launcher.py', target / 'launcher.py')
    shutil.copyfile(HERE / 'test_installer.py', target / 'test_installer.py')
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', required=True, type=Path)
    parser.add_argument('--authorization-assets', required=True, type=Path)
    args = parser.parse_args()
    print(prepare(args.target, args.authorization_assets))
