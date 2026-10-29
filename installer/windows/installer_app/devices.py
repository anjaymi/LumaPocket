"""USB device discovery and signed-IPA installation with bounded transfers."""
import asyncio
from datetime import datetime, timezone
import fnmatch
import os
from pathlib import Path
import plistlib
import subprocess
import uuid
import zipfile

from .paths import data_dir, private_environment
from .tooling import FLAGS, ensure_tools


def inspect_ipa(path, udid, decode_profile):
    path = Path(path)
    if path.suffix.lower() != '.ipa' or not path.is_file() or path.stat().st_size > 512 * 1024 * 1024:
        raise ValueError('invalid_ipa_file')
    try:
        with zipfile.ZipFile(path) as package:
            names = package.namelist()
            apps = [n[:-len('Info.plist')] for n in names
                    if n.startswith('Payload/') and n.endswith('.app/Info.plist') and n.count('/') == 2]
            if len(apps) != 1 or len(names) != len(set(names)):
                raise ValueError('invalid_ipa_layout')
            app = apps[0]
            profile_path = app + 'embedded.mobileprovision'
            if profile_path not in names:
                raise ValueError('ipa_not_signed')
            if package.getinfo(profile_path).file_size > 1024 * 1024 or package.getinfo(app + 'Info.plist').file_size > 1024 * 1024:
                raise ValueError('invalid_ipa_layout')
            info = plistlib.loads(package.read(app + 'Info.plist'))
            profile = decode_profile(package.read(profile_path))
    except (zipfile.BadZipFile, plistlib.InvalidFileException, KeyError):
        raise ValueError('invalid_ipa_file') from None
    expires = profile.get('ExpirationDate')
    if not isinstance(expires, datetime) or expires.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
        raise ValueError('ipa_profile_expired')
    if udid not in profile.get('ProvisionedDevices', []):
        raise ValueError('ipa_does_not_match_device')
    bundle = info.get('CFBundleIdentifier', '')
    app_id = profile.get('Entitlements', {}).get('application-identifier', '')
    team = profile.get('TeamIdentifier', [])
    if (not bundle or len(team) != 1 or not app_id.startswith(team[0] + '.') or
            not fnmatch.fnmatchcase(team[0] + '.' + bundle, app_id)):
        raise ValueError('ipa_profile_bundle_mismatch')
    return {'name': info.get('CFBundleDisplayName', info.get('CFBundleName', bundle)),
            'bundle': bundle, 'expires': expires.isoformat() + 'Z'}


def decode_mobileprovision(data):
    exe = data_dir() / 'tools' / 'git' / 'usr' / 'bin' / 'openssl.exe'
    result = subprocess.run([str(exe), 'cms', '-verify', '-inform', 'DER', '-noverify'], input=data,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=private_environment(),
                            timeout=20, creationflags=FLAGS)
    if result.returncode or len(result.stdout) > 1024 * 1024:
        raise ValueError('invalid_mobileprovision')
    return plistlib.loads(result.stdout)


async def _devices():
    from pymobiledevice3.usbmux import list_devices
    from pymobiledevice3.lockdown import create_using_usbmux
    try:
        devices = await asyncio.wait_for(list_devices(), timeout=8)
    except (OSError, asyncio.TimeoutError):
        raise ValueError('apple_device_driver_unavailable') from None
    found = []
    for device in devices:
        if not device.is_usb:
            continue
        info = {'udid': device.serial, 'name': 'Apple 设备', 'trusted': False}
        try:
            client = await asyncio.wait_for(create_using_usbmux(serial=device.serial, connection_type='USB',
                                                              autopair=False, label='LumaPocket Installer'), timeout=5)
            try:
                info.update(name=client.all_values.get('DeviceName', 'Apple 设备'), trusted=True,
                            version=client.product_version)
            finally:
                await client.close()
        except Exception:
            info['name'] = 'Apple 设备（请解锁并信任电脑）'
        found.append(info)
    return found


def list_connected():
    return asyncio.run(_devices())


async def _install(path, udid, emit):
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.afc import AfcService
    from pymobiledevice3.services.installation_proxy import InstallationProxyService

    emit('status', '请保持设备解锁，并在设备上选择“信任”这台电脑…')
    client = await create_using_usbmux(serial=udid, connection_type='USB', autopair=True,
                                      pair_timeout=45, label='LumaPocket Installer',
                                      pairing_records_cache_folder=data_dir() / 'pairing')
    remote = '/PublicStaging/LumaPocketInstaller/' + uuid.uuid4().hex + '.ipa'
    try:
        async with AfcService(client) as afc:
            await afc.makedirs('/PublicStaging/LumaPocketInstaller')
            handle = await afc.fopen(remote, 'w')
            try:
                size, sent, last = path.stat().st_size, 0, -1
                with path.open('rb') as source:
                    while chunk := source.read(1024 * 1024):
                        await afc.fwrite(handle, chunk)
                        sent += len(chunk)
                        percent = int(sent * 100 / size)
                        if percent != last:
                            emit('install_progress', {'stage': 'transfer', 'percent': percent})
                            last = percent
            finally:
                await afc.fclose(handle)
            try:
                emit('status', '已传输到设备，正在安装；请保持连接…')
                async with InstallationProxyService(client) as proxy:
                    def progress(percent, *args):
                        emit('install_progress', {'stage': 'install', 'percent': int(percent)})
                    await proxy.send_package('Install', {}, progress, remote)
            finally:
                try:
                    await afc.rm_single(remote, force=True)
                except Exception:
                    pass
    finally:
        await client.close()


def install_ipa(path, udid, emit):
    ensure_tools(emit)
    info = inspect_ipa(path, udid, decode_mobileprovision)
    emit('ipa_checked', info)
    try:
        asyncio.run(asyncio.wait_for(_install(Path(path), udid, emit), timeout=600))
    except Exception as error:
        value = str(error).lower()
        if any(x in value for x in ('pair', 'trust', 'password', 'passcode')):
            raise ValueError('device_trust_required') from None
        if any(x in value for x in ('verification', '0xe800', 'signature', 'provision')):
            raise ValueError('device_rejected_signature') from None
        if isinstance(error, (OSError, ConnectionError)):
            raise ValueError('device_connection_lost') from None
        raise ValueError('device_install_failed') from None
