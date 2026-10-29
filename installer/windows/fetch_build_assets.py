"""Fetch public, pinned build inputs; never use an account or signing profile."""
import argparse
import hashlib
from pathlib import Path
import urllib.request
import zipfile

import certifi

BASE = 'https://github.com/anjaymi/LumaPocket/releases/download/signer-compat-20261029-r2/'
WINDOWS = 'b0723ee840d10bf9402142866f9335fc0341278c361f401455b59932a074726e'
SIGNER = '848c660ae1de046deaba8d8f80048075e32cad7473464458ce1a5d9533d0202e'
SOURCE = 'fdb21a1a7c337da5a97e3b56cb910c60f2ed22fd574a98c4958cb972ce6fdf34'
APPLE = 'b0b1730ecbc7ff4505142c49f1295e6eda6bcaed7e2c68c5be91b5a11001f024'
RUNTIME = 'de55adfe0d9a9a4a2219ed8b218116a2d0690810916b7425fbc0b51647aaab6a'


def fetch(url, path, digest):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
        return
    request = urllib.request.Request(url, headers={'User-Agent': 'LumaPocket-build'})
    with urllib.request.urlopen(request, timeout=60) as response:
        content = response.read(128 * 1024 * 1024 + 1)
    if len(content) > 128 * 1024 * 1024 or hashlib.sha256(content).hexdigest() != digest:
        raise ValueError('public build input did not match pinned checksum')
    path.write_bytes(content)


def main(output):
    output.mkdir(parents=True, exist_ok=True)
    signer = output / 'signer-recovery-40866853470'
    archive = signer / 'sidesign-windows-x64.zip'
    fetch(BASE + archive.name, archive, WINDOWS)
    with zipfile.ZipFile(archive) as package:
        names = [n for n in package.namelist() if Path(n).name == 'sidesign.exe']
        if len(names) != 1 or package.getinfo(names[0]).file_size > 128 * 1024 * 1024:
            raise ValueError('unexpected public signer archive')
        binary = package.read(names[0])
    if hashlib.sha256(binary).hexdigest() != SIGNER:
        raise ValueError('signer executable did not match pinned checksum')
    (signer / 'windows').mkdir(exist_ok=True)
    (signer / 'windows/sidesign.exe').write_bytes(binary)
    fetch(BASE + 'sidesign-compat-source.tar.gz', signer / 'sidesign-compat-source.tar.gz', SOURCE)
    ca = output / 'AppleIncRootCertificate.cer'
    fetch('https://www.apple.com/appleca/AppleIncRootCertificate.cer', ca, APPLE)
    import ssl
    (output / 'apple_trust_bundle.pem').write_bytes(Path(certifi.where()).read_bytes() + b'\n' +
                                                 ssl.DER_cert_to_PEM_cert(ca.read_bytes()).encode())
    runtime = Path(__file__).resolve().parents[2] / 'signing/windows-runtime.zip'
    fetch('https://raw.githubusercontent.com/anjaymi/LumaPocket/a5f7ec78de7bfe580650ff526f3565a4ce783aa3/signing/windows-runtime.zip', runtime, RUNTIME)
    print('Verified public build resources: ' + str(output))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args().output.resolve())
