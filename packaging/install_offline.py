#!/usr/bin/python3
"""Verify an offline bundle and install exclusively from its local APT repository."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def verify(bundle):
    """Reject missing, altered, unsafe, or unlisted payload files before invoking APT."""
    for path in bundle.rglob('*'):
        if path.is_symlink():
            raise ValueError(f'Unsafe bundle path: {path.relative_to(bundle)}')
    checksums = json.loads((bundle / 'checksums.json').read_text())
    actual = {path.relative_to(bundle).as_posix() for path in bundle.rglob('*')
              if path.is_file() and path != bundle / 'checksums.json'}
    if actual != set(checksums):
        raise ValueError('Bundle inventory differs from checksums.json')
    for name, expected in checksums.items():
        path = bundle / name
        if path.is_symlink() or not path.resolve().is_relative_to(bundle.resolve()):
            raise ValueError(f'Unsafe bundle path: {name}')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                raise ValueError(f'Checksum mismatch: {name}')
    return json.loads((bundle / 'manifest.json').read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    bundle = Path(__file__).resolve().parent
    manifest = verify(bundle)
    print(f'Verified {len(manifest["packages"])} packages and supporting files.')
    if args.verify_only:
        return
    if os.geteuid() != 0:
        raise SystemExit('Run installation with sudo')
    if 'VERSION_CODENAME=trixie' not in Path('/etc/os-release').read_text():
        raise SystemExit('Trixie is required')
    if subprocess.check_output(['dpkg', '--print-architecture'], text=True).strip() != 'arm64':
        raise SystemExit('arm64 is required')
    if any(char.isspace() for char in str(bundle)):
        raise SystemExit('Extract the bundle to a path without whitespace')
    with tempfile.TemporaryDirectory(prefix='optic-coyote-offline-') as temporary:
        work = Path(temporary)
        work.chmod(0o755)
        (work / 'lists/partial').mkdir(parents=True)
        (work / 'sources.list').write_text(f'deb [trusted=yes] {bundle.as_uri()} ./\n')
        # The temporary source list excludes host repositories from dependency downloads.
        common = ['apt-get', '-o', f'Dir::Etc::sourcelist={work / "sources.list"}',
                  '-o', 'Dir::Etc::sourceparts=-', '-o', f'Dir::State::lists={work / "lists"}',
                  '-o', 'Acquire::http::Proxy=false', '-o', 'Acquire::https::Proxy=false']
        subprocess.run([*common, 'update', '--error-on=any'], check=True)
        subprocess.run([*common, '--no-install-recommends', '--no-remove', 'install',
                        f'project-optic-coyote={manifest["version"]}'], check=True)
    print('Installed. Run sudo optic-coyote-setup; services have not been started.')


if __name__ == '__main__':
    main()
