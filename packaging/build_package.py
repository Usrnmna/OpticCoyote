#!/usr/bin/env python3
"""Build a Debian package from an explicit source inventory using dpkg-deb.

Run on Linux or WSL. A temporary staging tree excludes local configuration,
reports, caches, and tests. Python source remains inspectable after installation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
APPLICATION_FILES = {
    'rpi-ahd-selector': ['selector.py', 'control.py', 'diagnose_adapter.py', 'config.json', 'diagnostic.json'],
    'rpi-oled-bridge': ['bridge.py', 'reverse_control.py', 'diagnose_reverse.py', 'reverse.json', 'reverse-diagnostic.json'],
    'rpi-buzzer': ['buzzer.py', 'buzzer.json'],
    'tools': ['check_trigger_setup.py'],
    'packaging': ['optic_coyote_cli.py'],
}
COMMANDS = ('camera', 'control', 'reverse', 'buzzer', 'diagnose-camera', 'diagnose-reverse', 'check', 'setup')


def write_text(path, text, mode=0o644):
    """Write UTF-8/LF files with explicit package permissions on any source checkout."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')
    path.chmod(mode)


def stage(destination, version):
    """Assemble application, templates, wrappers, units, and package metadata."""
    destination.mkdir(parents=True, exist_ok=True)
    destination.chmod(0o755)
    library = destination / 'usr/lib/project-optic-coyote'
    for directory, names in APPLICATION_FILES.items():
        for name in names:
            relative = Path(directory) / name
            write_text(library / relative, (ROOT / relative).read_text(encoding='utf-8'))
    for name in COMMANDS:
        write_text(destination / 'usr/bin' / ('optic-coyote-' + name),
                   '#!/bin/sh\nexec /usr/bin/python3 -B /usr/lib/project-optic-coyote/packaging/optic_coyote_cli.py '
                   + name + ' "$@"\n', 0o755)
    for name in ('camera', 'reverse'):
        unit = f'optic-coyote-{name}.service'
        write_text(destination / 'usr/lib/systemd/system' / unit, (ROOT / 'packaging' / unit).read_text())
    # Keep the README and documentation tree together for guide-to-guide links.
    for source in [ROOT / 'README.md', ROOT / 'draft-gpio-link/README.md',
                   ROOT / 'docs/images/project-banner.png',
                   ROOT / 'docs/images/project-status.svg',
                   ROOT / 'docs/images/oled-distance-layout.png',
                   *sorted((ROOT / 'docs').glob('*.md'))]:
        target = destination / 'usr/share/doc/project-optic-coyote' / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Preserve authored documentation bytes, including older Windows encodings.
        target.write_bytes(source.read_bytes())
        target.chmod(0o644)
    dependencies = (ROOT / 'packaging/dependencies.txt').read_text().split()
    installed_bytes = sum(path.stat().st_size for path in destination.rglob('*') if path.is_file())
    installed_kib = (installed_bytes + 1023) // 1024
    control = (
        f'Package: project-optic-coyote\nVersion: {version}\nArchitecture: all\n'
        'Maintainer: Project Optic Coyote packaging <packaging@localhost>\n'
        'Section: misc\nPriority: optional\n'
        f'Installed-Size: {installed_kib}\n'
        f'Depends: {", ".join(dependencies)}\n'
        'Description: Local camera selector and reverse sensor OLED services\n'
        ' Raspberry Pi 5 software for Raspberry Pi OS Lite Trixie arm64.\n'
        ' Hardware assignment and service activation require explicit setup.\n'
    )
    write_text(destination / 'DEBIAN/control', control)
    for script in ('postinst', 'prerm', 'postrm'):
        write_text(destination / 'DEBIAN' / script, (ROOT / 'packaging' / script).read_text(), 0o755)
    files = sorted(p for p in destination.rglob('*') if p.is_file() and 'DEBIAN' not in p.parts)
    write_text(destination / 'DEBIAN/md5sums', ''.join(
        f'{hashlib.md5(path.read_bytes()).hexdigest()}  {path.relative_to(destination).as_posix()}\n' for path in files))
    # A restrictive builder umask must not prevent the service account reading code.
    for directory in destination.rglob('*'):
        if directory.is_dir():
            directory.chmod(0o755)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist')
    parser.add_argument('--version', default=(ROOT / 'packaging/VERSION').read_text().strip())
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9][A-Za-z0-9.+~]*', args.version):
        parser.error('Version must start with a digit and contain Debian version characters')
    if not shutil.which('dpkg-deb'):
        parser.error('dpkg-deb is required; run this builder on Linux or WSL')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir.resolve() / f'project-optic-coyote_{args.version}_all.deb'
    with tempfile.TemporaryDirectory(prefix='optic-coyote-package-') as temporary:
        staged = Path(temporary)
        stage(staged, args.version)
        epoch = int(os.environ.get('SOURCE_DATE_EPOCH', '1792108800'))
        for path in staged.rglob('*'):
            os.utime(path, (epoch, epoch))
        os.utime(staged, (epoch, epoch))
        subprocess.run(['dpkg-deb', '--root-owner-group', '-Zxz', '--build', str(staged), str(output)],
                       check=True, env={**os.environ, 'SOURCE_DATE_EPOCH': str(epoch)})
    manifest = {'package': output.name, 'version': args.version,
                'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
                'supported_os': 'Raspberry Pi OS Lite 64-bit Trixie',
                'hardware_validation': 'Not performed'}
    write_text(output.with_suffix('.json'), json.dumps(manifest, indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
