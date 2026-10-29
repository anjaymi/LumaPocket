"""Build a standalone Windows client from explicit, credential-free inputs."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import ssl
import zipfile

from prepare_build import HERE, ROOT, prepare
from installer_app import __version__


def build(output, resources, icon):
    stage = prepare(output / 'stage', resources)
    assets = stage / 'installer_app' / 'assets'
    shutil.copyfile(icon, assets / 'app_icon.ico')
    sources = assets / 'source.zip'
    with zipfile.ZipFile(sources, 'w', zipfile.ZIP_DEFLATED) as package:
        for folder, prefix in ((HERE, 'installer/windows'), (ROOT / 'signing', 'signing')):
            for file in folder.rglob('*'):
                if file.is_file() and '__pycache__' not in file.parts and (file.suffix in ('.py', '.txt', '.md', '.json', '.yml', '.yaml') or file.name == 'LICENSE'):
                    package.write(file, prefix + '/' + file.relative_to(folder).as_posix())
        signer_source = resources / 'signer-recovery-40866853470' / 'sidesign-compat-source.tar.gz'
        package.write(signer_source, 'third-party/sidesign-compat-source.tar.gz')
        distribution = importlib.metadata.distribution('pymobiledevice3')
        for relative in distribution.files:
            if str(relative).startswith('pymobiledevice3/') and Path(relative).suffix == '.py' or 'licenses/' in str(relative):
                file = Path(distribution.locate_file(relative))
                if file.is_file():
                    package.write(file, 'third-party/' + str(relative).replace('\\', '/'))
        for name, file in (
            ('Python-PSF.txt', Path(sys.base_prefix) / 'LICENSE.txt'),
            ('Tcl-Tk.txt', Path(sys.base_prefix) / 'tcl/tk8.6/license.terms'),
        ):
            if file.is_file():
                package.write(file, 'third-party/licenses/' + name)
        for dependency in ('cryptography', 'websockets', 'bytestruct', 'pygnuutils', 'pywin32',
                           'rich', 'prompt_toolkit', 'questionary', 'zeroconf', 'requests'):
            dist = importlib.metadata.distribution(dependency)
            for relative in dist.files or []:
                if 'licenses/' in str(relative):
                    file = Path(dist.locate_file(relative))
                    if file.is_file():
                        package.write(file, 'third-party/' + str(relative).replace('\\', '/'))
    notices = [
        f'LumaPocket 安装助手 {__version__} · 实验版',
        '安装助手源代码与所用 GPL 组件源码包含在 source.zip。',
        'SideSign: https://github.com/SideStore/SideSign (GPL-3.0)',
        'Compatibility build: https://github.com/anjaymi/LumaPocket/releases/tag/signer-compat-20261029-r2',
        'pymobiledevice3: https://github.com/doronz88/pymobiledevice3 (GPL-3.0-or-later)',
        'GitHub CLI (MIT) and PortableGit are downloaded from their official pinned releases on first use.',
        'Swift/ICU licenses are included in windows-runtime.zip and the extracted runtime directory.',
        'Python (PSF), Tcl/Tk and dependency licenses are included in source.zip under third-party/.',
        'This package includes no Apple account, certificate, device authorization or GitHub login.',
    ]
    (assets / 'NOTICES.txt').write_text('\n'.join(notices), encoding='utf-8')
    # Include license/metadata for each runtime dependency, independently of its
    # Python import path, without collecting optional device-development tools.
    metadata = []
    for name in ('pymobiledevice3', 'cryptography', 'websockets', 'bytestruct', 'pygnuutils',
                 'pywin32', 'rich', 'prompt_toolkit', 'questionary', 'zeroconf', 'requests'):
        metadata.extend(['--copy-metadata', name])
    # The bundled development Python adds a public CA rejection policy to
    # SSLContext.__new__. Preserve that trust policy in frozen deployments;
    # without its data file every Python HTTPS request fails before connecting.
    runtime_data = []
    rejection_policy = Path(ssl.__file__).parent / 'codex-rejected-cas.pem'
    if rejection_policy.is_file():
        runtime_data = ['--add-data', str(rejection_policy) + ';.']
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--windowed', '--onefile', '--noupx',
        '--name', 'LumaPocket-Installer', '--paths', str(stage), '--distpath', str(output / 'dist'),
        '--workpath', str(output / 'pyinstaller-work'), '--specpath', str(output),
        '--icon', str(icon), '--add-data', str(assets) + ';installer_app/assets',
        '--collect-data', 'pymobiledevice3', '--hidden-import', 'pymobiledevice3.osu.win_util',
        '--hidden-import', 'win32security', '--exclude-module', 'IPython', '--exclude-module', 'av',
        '--exclude-module', 'pytest', '--exclude-module', 'matplotlib', '--exclude-module', 'numpy',
        *runtime_data, *metadata, str(stage / 'launcher.py')]
    subprocess.run(command, check=True)
    executable = output / 'dist' / 'LumaPocket-Installer.exe'
    manifest = {'version': __version__, 'file': executable.name, 'bytes': executable.stat().st_size,
                'sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
                'signerVersion': '0.1.7-lumapocket-v3.2', 'containsPersonalAuthorization': False}
    (output / 'dist' / 'installer-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--authorization-assets', required=True, type=Path)
    parser.add_argument('--icon', required=True, type=Path)
    args = parser.parse_args()
    build(args.output.resolve(), args.authorization_assets.resolve(), args.icon.resolve())
