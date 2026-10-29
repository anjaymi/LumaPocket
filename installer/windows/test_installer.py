from datetime import datetime, timedelta, timezone
from pathlib import Path
import plistlib
import queue
import tempfile
import unittest
import zipfile

from installer_app.devices import inspect_ipa
from installer_app.paths import private_environment
from installer_app.tasks import Task


class InstallerTests(unittest.TestCase):
    def test_unsigned_and_wrong_device_packages_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.ipa'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('Payload/Test.app/Info.plist', plistlib.dumps({'CFBundleIdentifier': 'io.fixture.app'}))
            with self.assertRaisesRegex(ValueError, 'ipa_not_signed'):
                inspect_ipa(path, 'fixture-device', lambda _: {})
            with zipfile.ZipFile(path, 'a') as archive:
                archive.writestr('Payload/Test.app/embedded.mobileprovision', b'fixture-only')
            profile = {'ExpirationDate': datetime.now(timezone.utc) + timedelta(days=1),
                       'ProvisionedDevices': ['other-fixture-device'], 'TeamIdentifier': ['FIXTURE123'],
                       'Entitlements': {'application-identifier': 'FIXTURE123.io.fixture.app'}}
            with self.assertRaisesRegex(ValueError, 'ipa_does_not_match_device'):
                inspect_ipa(path, 'fixture-device', lambda _: profile)
            profile['ProvisionedDevices'] = ['fixture-device']
            self.assertEqual(inspect_ipa(path, 'fixture-device', lambda _: profile)['bundle'], 'io.fixture.app')
            profile['ExpirationDate'] = datetime.now(timezone.utc) - timedelta(seconds=1)
            with self.assertRaisesRegex(ValueError, 'ipa_profile_expired'):
                inspect_ipa(path, 'fixture-device', lambda _: profile)

    def test_credentials_are_not_inherited(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {'GH_TOKEN': 'fixture-not-a-token', 'GITHUB_TOKEN': 'fixture-not-a-token'}):
            env = private_environment()
            self.assertNotIn('GH_TOKEN', env)
            self.assertNotIn('GITHUB_TOKEN', env)

    def test_windowed_worker_pipes_with_synthetic_inputs(self):
        events = queue.Queue()
        task = Task(lambda name, detail: events.put((name, detail)))
        task.start('fixture', udid='00000000-0000000000000000', account='fixture@example.invalid')
        got_complete = False
        try:
            while True:
                name, detail = events.get(timeout=25)
                if name == 'password':
                    task.submit('offline-fixture-only')
                elif name == 'fixture_complete':
                    got_complete = True
                elif name == 'done':
                    self.assertEqual(detail['code'], 0)
                    break
        finally:
            if task.process and task.process.poll() is None:
                task.cancel()
        self.assertTrue(got_complete)


if __name__ == '__main__':
    unittest.main()
