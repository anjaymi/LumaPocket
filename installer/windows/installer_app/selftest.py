"""Offline checks for the actual frozen app; never load a real account."""
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import ssl
import subprocess
import tempfile


def run(report_path):
    report = {'schema': 1, 'realAppleAccountUsed': False, 'realDeviceUsed': False, 'checks': {}}
    try:
        from .native import hide_worker_consoles
        hide_worker_consoles()
        with tempfile.TemporaryDirectory(prefix='lp-exe-selftest-') as directory:
            os.environ['LOCALAPPDATA'] = directory
            from .paths import ASSETS, data_dir, private_environment
            from .backend import SIGNER_HASH, install_signer
            from .accounts import account_info
            from .tooling import FLAGS
            from .tasks import Task
            from lumapocket_signing.local_key import dpapi
            from lumapocket_signing.guard_probe import check_guard
            import pymobiledevice3.usbmux
            import pymobiledevice3.lockdown
            import pymobiledevice3.services.installation_proxy
            report['checks']['usbApiImports'] = True
            context = ssl.create_default_context()
            report['checks']['pythonHttpsContext'] = context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
            report['checks']['signerDigest'] = hashlib.sha256((ASSETS / 'sidesign.exe').read_bytes()).hexdigest() == SIGNER_HASH
            report['checks']['noPrivateAssetFiles'] = not any(p.suffix in ('.dpapi', '.p12', '.mobileprovision') for p in ASSETS.rglob('*'))
            report['checks']['noBundledAccount'] = account_info() is None
            report['checks']['dpapiRoundTrip'] = dpapi(dpapi(b'offline-fixture-only'), decrypt=True) == b'offline-fixture-only'
            old = os.environ.get('GH_TOKEN')
            os.environ['GH_TOKEN'] = 'synthetic-must-not-inherit'
            report['checks']['noInheritedGitHubToken'] = 'GH_TOKEN' not in private_environment()
            if old is None:
                os.environ.pop('GH_TOKEN', None)
            else:
                os.environ['GH_TOKEN'] = old
            tool = install_signer(data_dir() / 'offline-tool')
            result = subprocess.run([str(tool), '--help'], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    timeout=30, creationflags=FLAGS, env=private_environment())
            report['checks']['nativeSignerStarts'] = result.returncode == 0
            probe = data_dir() / 'offline-probe'
            probe.mkdir()
            check_guard(tool, probe)
            report['checks']['nativePasswordPrompt'] = True
            events = queue.Queue()
            worker = Task(lambda name, detail: events.put((name, detail)))
            worker.start('fixture', udid='00000000-0000000000000000', account='fixture@example.invalid')
            complete = False
            try:
                while True:
                    name, detail = events.get(timeout=30)
                    if name == 'password':
                        worker.submit('offline-fixture-only')
                    elif name == 'fixture_complete':
                        complete = True
                    elif name == 'done':
                        report['checks']['windowedWorkerPipes'] = complete and detail['code'] == 0
                        break
            finally:
                if worker.process and worker.process.poll() is None:
                    worker.cancel()
        report['passed'] = all(report['checks'].values())
    except Exception as error:
        report['passed'] = False
        report['failureType'] = type(error).__name__
        if isinstance(error, ModuleNotFoundError) and error.name and re.fullmatch(r'[A-Za-z0-9_.]+', error.name):
            report['missingModule'] = error.name
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    return 0 if report['passed'] else 1
