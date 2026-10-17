#!/usr/bin/env python3
"""Resolve a complete Trixie arm64 dependency closure into an offline APT repository.

APT uses an empty installed-package database and isolated configuration. Signed
Debian and Raspberry Pi repositories authenticate downloads. No host packages,
architectures, sources, or installed state are changed.
"""
import argparse
import datetime
from email.utils import format_datetime
import hashlib
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

from build_package import ROOT, write_text


KEY_URLS = [
    'https://ftp-master.debian.org/keys/archive-key-13.asc',
    'https://ftp-master.debian.org/keys/archive-key-13-security.asc',
    'https://ftp-master.debian.org/keys/release-13.asc',
]
PI_KEYRING_URL = ('https://archive.raspberrypi.com/debian/pool/main/r/raspberrypi-archive-keyring/'
                  'raspberrypi-archive-keyring_2025.1+rpt1_all.deb')
PI_KEYRING_SHA256 = '2e727149d7acb8cc7f604e66d0049161039c8aa1eaf1175e54f9e69d963d60e4'
REPOSITORIES = [
    ('https://deb.debian.org/debian', 'trixie', 'main'),
    ('https://deb.debian.org/debian', 'trixie-updates', 'main'),
    ('https://security.debian.org/debian-security', 'trixie-security', 'main'),
    ('https://archive.raspberrypi.com/debian', 'trixie', 'main'),
]


def digest(path):
    """Hash package files without retaining the complete bundle in memory."""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def apt_configuration(work):
    """Prepare isolated APT directories and authenticated source definitions."""
    for name in ('lists/partial', 'archives/partial', 'keys', 'log', 'empty'):
        (work / name).mkdir(parents=True, exist_ok=True)
    key_paths = []
    for index, url in enumerate(KEY_URLS):
        path = work / 'keys' / f'archive-{index}.asc'
        with urllib.request.urlopen(url, timeout=60) as response:
            path.write_bytes(response.read())
        key_paths.append(path)
    # The legacy raspberrypi.gpg.key has a SHA-1 certification rejected by Trixie.
    # Pin the current official keyring package rather than relaxing APT policy.
    key_package = work / 'keys/raspberrypi-keyring.deb'
    with urllib.request.urlopen(PI_KEYRING_URL, timeout=60) as response:
        key_package.write_bytes(response.read())
    if digest(key_package) != PI_KEYRING_SHA256:
        raise ValueError('Raspberry Pi keyring package checksum mismatch')
    extracted = work / 'keys/raspberrypi'
    subprocess.run(['dpkg-deb', '--extract', str(key_package), str(extracted)], check=True)
    pi_key = work / 'keys/raspberrypi.gpg'
    shutil.copyfile(extracted / 'usr/share/keyrings/raspberrypi-archive-keyring.pgp', pi_key)
    key_paths.append(pi_key)
    sources = []
    for index, (url, suite, components) in enumerate(REPOSITORIES):
        keys = key_paths[:3] if index < 3 else key_paths[3:]
        sources.append(f'deb [arch=arm64 signed-by={",".join(map(str, keys))}] {url} {suite} {components}')
    write_text(work / 'sources.list', '\n'.join(sources) + '\n')
    write_text(work / 'status', '')
    write_text(work / 'preferences', '')
    config = f'''Dir::Etc::main "-";
Dir::Etc::parts "{work / 'empty'}";
Dir::Etc::sourcelist "{work / 'sources.list'}";
Dir::Etc::sourceparts "{work / 'empty'}";
Dir::Etc::preferences "{work / 'preferences'}";
Dir::Etc::preferencesparts "{work / 'empty'}";
Dir::State::status "{work / 'status'}";
Dir::State::lists "{work / 'lists'}";
Dir::State::extended_states "{work / 'extended_states'}";
Dir::Cache::archives "{work / 'archives'}";
Dir::Cache::pkgcache "{work / 'pkgcache.bin'}";
Dir::Cache::srcpkgcache "{work / 'srcpkgcache.bin'}";
Dir::Log "{work / 'log'}";
APT::Architecture "arm64";
APT::Architectures {{ "arm64"; }};
APT::Install-Recommends "false";
APT::Install-Suggests "false";
Acquire::Languages "none";
Acquire::Retries "3";
'''
    write_text(work / 'apt.conf', config)
    # APT's sandbox account must be able to read keys under a restrictive umask.
    for path in work.rglob('*'):
        path.chmod(0o755 if path.is_dir() else 0o644)
    return {**os.environ, 'APT_CONFIG': str(work / 'apt.conf')}


def write_repository(bundle):
    """Index exact package versions and hashes for local APT dependency solving."""
    entries, manifest = [], []
    for path in sorted((bundle / 'pool').glob('*.deb')):
        control = subprocess.check_output(['dpkg-deb', '--field', str(path)], text=True).rstrip()
        sha256 = digest(path)
        filename = path.relative_to(bundle).as_posix()
        entries.append(f'{control}\nFilename: {filename}\nSize: {path.stat().st_size}\nSHA256: {sha256}\n\n')
        fields = {}
        for line in control.splitlines():
            if line and not line[0].isspace() and ': ' in line:
                key, value = line.split(': ', 1)
                fields[key] = value
        if fields['Architecture'] not in ('arm64', 'all'):
            raise ValueError(f'Unexpected architecture: {path}')
        manifest.append({key.lower(): fields[key] for key in ('Package', 'Version', 'Architecture')} |
                        {'file': filename, 'sha256': sha256})
    write_text(bundle / 'Packages', ''.join(entries))
    (bundle / 'Packages.gz').write_bytes(gzip.compress(''.join(entries).encode(), mtime=0))
    write_release(bundle)
    return manifest


def write_release(bundle):
    """Describe available indexes so APT does not probe absent compression formats."""
    checksums = ''.join(f' {digest(bundle / name)} {(bundle / name).stat().st_size} {name}\n'
                        for name in ('Packages', 'Packages.gz'))
    write_text(bundle / 'Release', 'Origin: Project Optic Coyote\n'
               'Label: Optic Coyote offline installation\n'
               f'Date: {format_datetime(datetime.datetime.now(datetime.timezone.utc), usegmt=True)}\n'
               'Architectures: arm64 all\n'
               'Description: Local dependency snapshot; integrity checked by install.py\n'
               'SHA256:\n' + checksums)


def archive_metadata(member):
    """Normalize archive ownership and permissions independently of checkout mounts."""
    member.uid = member.gid = 0
    member.uname = member.gname = 'root'
    member.mode = 0o755 if member.isdir() or member.name.endswith('/install.py') else 0o644
    return member


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    package = args.package.resolve()
    version = subprocess.check_output(['dpkg-deb', '-f', str(package), 'Version'], text=True).strip()
    output = args.output_dir.resolve()
    if any(char.isspace() or char in '\",' for char in str(output)):
        parser.error('Offline output path must not contain whitespace, quotes, or commas')
    output.mkdir(parents=True, exist_ok=True)
    bundle = output / f'project-optic-coyote_{version}_trixie_arm64_offline'
    # Refuse accidental reuse: a previous dependency snapshot must remain intact.
    bundle.mkdir()
    work = Path(tempfile.mkdtemp(prefix=f'apt-work-{version}-', dir=output))
    work.chmod(0o755)
    environment = apt_configuration(work)
    subprocess.run(['apt-get', 'update', '--error-on=any'], env=environment, check=True)
    subprocess.run(['apt-get', '--download-only', '--no-install-recommends', '--yes',
                    'install', str(package)], env=environment, check=True)
    (bundle / 'pool').mkdir()
    shutil.copy2(package, bundle / 'pool' / package.name)
    for source in (work / 'archives').glob('*.deb'):
        shutil.copy2(source, bundle / 'pool' / source.name)
    packages = write_repository(bundle)
    # Resolve again using only the generated local repository and an empty status.
    local = work / 'local.list'
    write_text(local, f'deb [trusted=yes] {bundle.as_uri()} ./\n')
    subprocess.run(['apt-get', '-o', f'Dir::Etc::sourcelist={local}', 'update', '--error-on=any'],
                   env=environment, check=True)
    resolution = subprocess.check_output(['apt-get', '-o', f'Dir::Etc::sourcelist={local}',
                                         '--simulate', '--no-install-recommends', 'install',
                                         f'project-optic-coyote={version}'], env=environment, text=True)
    write_text(bundle / 'dependency-resolution.txt', resolution)
    write_text(bundle / 'install.py', (ROOT / 'packaging/install_offline.py').read_text(), 0o755)
    shutil.copytree(ROOT / 'docs', bundle / 'docs', ignore=shutil.ignore_patterns('_build', '.cache'))
    shutil.copyfile(ROOT / 'README.md', bundle / 'README.md')
    # Preserve the historical-guide link used by the documentation index.
    (bundle / 'draft-gpio-link').mkdir()
    shutil.copyfile(ROOT / 'draft-gpio-link/README.md', bundle / 'draft-gpio-link/README.md')
    write_text(bundle / 'INSTALL.md', '# Offline installation\n\n'
               'See [installation and setup](docs/installation-package.md) for the complete procedure.\n\n'
               'Run `python3 install.py --verify-only`, then `sudo python3 install.py`, '
               'then `sudo optic-coyote-setup` on the target Pi.\n'
               'Successful setup enables both services for boot without starting them immediately.\n')
    manifest = {'version': version, 'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'baseline': 'Raspberry Pi OS Lite Debian 13 Trixie arm64; existing bootable OS required',
                'resolution': 'Complete dependency closure resolved from empty installed-package status',
                'repositories': REPOSITORIES, 'key_urls': KEY_URLS,
                'raspberrypi_keyring': {'url': PI_KEYRING_URL, 'sha256': PI_KEYRING_SHA256},
                'packages': packages,
                'verification': 'Local repository APT simulation passed; hardware not tested'}
    write_text(bundle / 'manifest.json', json.dumps(manifest, indent=2) + '\n')
    checksums = {path.relative_to(bundle).as_posix(): digest(path)
                 for path in sorted(bundle.rglob('*')) if path.is_file()}
    write_text(bundle / 'checksums.json', json.dumps(checksums, indent=2) + '\n')
    archive = Path(str(bundle) + '.tar.gz')
    with tarfile.open(archive, 'w:gz') as stream:
        stream.add(bundle, arcname=bundle.name, filter=archive_metadata)
    write_text(archive.with_suffix(archive.suffix + '.sha256'), f'{digest(archive)}  {archive.name}\n')
    print(f'{archive}: {len(packages)} packages')


if __name__ == '__main__':
    main()
