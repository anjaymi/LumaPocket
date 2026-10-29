"""Run signing in a private child process, with only safe UI events retained."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import traceback
import zipfile

from .paths import ASSETS, data_dir, private_environment

SIGNER_HASH = '848c660ae1de046deaba8d8f80048075e32cad7473464458ce1a5d9533d0202e'


def emit(name, detail=None):
    print('LP_EVENT ' + json.dumps({'name': name, 'detail': detail}, ensure_ascii=False), flush=True)


def install_signer(root):
    from .tooling import check_cpp_runtime
    check_cpp_runtime()
    from lumapocket_signing import tool
    from lumapocket_signing.common import SigningError
    binary = (ASSETS / 'sidesign.exe').read_bytes()
    if hashlib.sha256(binary).hexdigest() != SIGNER_HASH:
        raise SigningError('updated_signer_integrity_check_failed')
    config = json.loads((ASSETS / 'toolchain.json').read_text())
    archive = ASSETS / 'windows-runtime.zip'
    if hashlib.sha256(archive.read_bytes()).hexdigest() != config['windowsRuntime']['sha256']:
        raise SigningError('updated_signer_integrity_check_failed')
    target = Path(root) / 'bin'
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as package:
        for item in package.infolist():
            name = tool.safe_name(item.filename)
            if '/' in name or item.file_size > 128 * 1024 * 1024:
                raise SigningError('unsafe_runtime_archive')
            tool.write_verified_member(target / name, package.read(item))
    destination = target / 'sidesign.exe'
    tool.write_verified_member(destination, binary)
    return destination


def configure_signing():
    from lumapocket_signing import local, local_repositories
    from lumapocket_signing.common import SigningError
    from lumapocket_signing.v3_guard import v3_only_server
    from .accounts import load_account
    from .v3_provision import provision, write_machine, SERVER

    account = load_account()
    original_gh = local_repositories.gh

    def private_gh(arguments, data=None, missing_ok=False, token=None):
        if arguments[:2] == ['auth', 'token']:
            if '--user' in arguments and arguments[arguments.index('--user') + 1].lower() != account['login'].lower():
                raise SigningError('github_token_belongs_to_another_owner')
            return account['token'].encode()
        return original_gh(arguments, data=data, missing_ok=missing_ok, token=token or account['token'])

    local_repositories.gh = private_gh

    original_run = local.run_private

    def isolated_login(command, root, stage, *args, **kwargs):
        if stage != 'local_apple_authorization':
            return original_run(command, root, stage, *args, **kwargs)
        command = list(command)
        server_index = command.index('--server') + 1
        if command[server_index].rstrip('/') != SERVER:
            raise SigningError('windows_bridge_requires_sidestore_v3')
        machine = Path(command[command.index('--machine-path') + 1])
        if not machine.exists():
            print('Preparing isolated V3 device authentication...', flush=True)
            try:
                identifier, adi, routing = provision()
                if routing != '17106176':
                    raise ValueError('unsupported_routing_info')
                write_machine(machine, command[command.index('--machine-password') + 1], identifier, adi)
            except Exception:
                raise SigningError('v3_device_setup_failed_check_network') from None
        with v3_only_server(SERVER) as guarded:
            command[server_index] = guarded
            return original_run(command, root, stage, *args, **kwargs)

    original_authorize = local.authorize

    def authorize(home, args, password, scope):
        github = local.client(scope)
        expected = json.loads((ASSETS / 'signing-fingerprints.json').read_text())
        for name, digest in expected.items():
            item = github.get('contents/signing/' + name + '?ref=main', missing_ok=True)
            if not item or item.get('encoding') != 'base64':
                raise SigningError('personal_signing_repository_needs_security_update')
            remote = base64.b64decode(item['content'])
            if hashlib.sha256(remote).hexdigest() != digest:
                raise SigningError('personal_signing_repository_needs_security_update')
        return original_authorize(home, args, password, scope)

    original_download = local.download

    def download(home, password, scope):
        source = Path(original_download(home, password, scope)).resolve()
        if not source.is_relative_to((data_dir() / 'state').resolve()):
            raise SigningError('unexpected_signed_package_path')
        folder = data_dir() / 'downloads' / scope.owner
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / source.name
        shutil.copy2(source, destination)
        emit('ipa_ready', str(destination))
        return destination

    local.install = install_signer
    local.run_private = isolated_login
    local.authorize = authorize
    local.download = download
    return local


def run_signing(action, repository_name='LumaPocket-Cloud'):
    local = configure_signing()
    if action == 'download':
        emit('status', '正在下载并校验最新签名包，请稍候…')
    arguments = ['local.py', action, '--home', str(data_dir() / 'state'), '--repo-name', repository_name]
    sys.argv = arguments
    local.main()
    if action in ('onboard', 'authorize', 'publish'):
        emit('status', '正在下载经过验证的签名 IPA…')
        sys.argv = ['local.py', 'download', '--home', str(data_dir() / 'state')]
        local.main()


def main(arguments):
    from .native import hide_worker_consoles
    hide_worker_consoles()
    env = private_environment()
    os.environ.update(env)
    for name in ('GH_TOKEN', 'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN'):
        os.environ.pop(name, None)
    action = arguments[0] if arguments else ''
    try:
        if action == 'prepare':
            from .tooling import ensure_tools
            ensure_tools(emit)
            emit('prepared')
        elif action == 'trust-apple-root':
            from .tooling import install_apple_root
            install_apple_root()
            emit('trusted_apple_root')
        elif action == 'github-login':
            from .tooling import ensure_tools
            from .accounts import login
            gh = ensure_tools(emit)
            login(gh, emit)
        elif action == 'devices':
            from .devices import list_connected
            emit('devices', list_connected())
        elif action == 'install':
            from .devices import install_ipa
            install_ipa(arguments[1], arguments[2], emit)
            emit('installed')
        elif action in ('onboard', 'authorize', 'download', 'publish'):
            from .tooling import ensure_tools
            ensure_tools(emit)
            run_signing(action, arguments[1] if len(arguments) > 1 else 'LumaPocket-Cloud')
        elif action == 'fixture':
            print('iPhone / iPad UDID (from Apple Devices/iTunes): ', end='', flush=True)
            input()
            print('Apple Account email: ', end='', flush=True)
            input()
            print('Enter password for fixture@example.invalid: ', end='', flush=True)
            input()
            emit('fixture_complete')
        else:
            raise ValueError('unsupported_action')
    except Exception as error:
        from lumapocket_signing.common import SigningError
        # Never retain exception messages/locals from account operations. These
        # code locations and class names are sufficient for packaging failures.
        diagnostic = {'exceptionType': type(error).__name__, 'frames': [
            {'file': Path(frame.filename).name, 'function': frame.name, 'line': frame.lineno}
            for frame in traceback.extract_tb(error.__traceback__)[-8:]]}
        if isinstance(error, ModuleNotFoundError):
            diagnostic['missingModule'] = error.name
        emit('diagnostic', diagnostic)
        known = str(error) if isinstance(error, (SigningError, ValueError)) else type(error).__name__
        if not known or len(known) > 100 or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_' for c in known):
            known = 'operation_failed'
        emit('error_code', known)
        return 1
    return 0
