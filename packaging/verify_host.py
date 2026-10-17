#!/usr/bin/env python3
"""Run hardware-free Python/C++ regression, shell syntax, and service-definition checks."""
from pathlib import Path
import os
import tempfile
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    """Keep each suite isolated to avoid colliding component module names."""
    output = ROOT / 'dist/verification'
    output.mkdir(parents=True, exist_ok=True)
    for suite in ('packaging', 'rpi-ahd-selector', 'rpi-oled-bridge', 'rpi-buzzer', 'tests/integration'):
        log = output / (suite.replace('/', '-') + '.log')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', suite,
                                     '-p', 'test_*.py', '-v'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                    env={**os.environ, 'LC_ALL': 'C', 'LANG': 'C', 'LANGUAGE': 'C'})
        print(f'{suite}: {"PASS" if result.returncode == 0 else "FAIL"} ({log})', flush=True)
        if result.returncode:
            print(log.read_text())
            return result.returncode
    for name in ('postinst', 'prerm', 'postrm'):
        subprocess.run(['sh', '-n', str(ROOT / 'packaging' / name)], check=True)
    # Native builds exercise firmware logic against host stubs, not Nano peripherals.
    with tempfile.TemporaryDirectory(prefix='optic-coyote-firmware-') as temporary:
        for directory, name in (('nano', 'serial'), ('nano', 'reverse'),
                                ('display', 'display'), ('display', 'reverse_display')):
            executable = Path(temporary) / name
            with (output / f'firmware-{name}.log').open('w') as stream:
                subprocess.run(['g++', '-std=c++11', '-Wall', '-Wextra', '-Werror',
                                '-I', str(ROOT / 'tests' / directory),
                                str(ROOT / 'tests' / directory / f'test_{name}.cpp'),
                                '-o', str(executable)], check=True, stdout=stream, stderr=subprocess.STDOUT)
                subprocess.run([str(executable)], check=True, stdout=stream, stderr=subprocess.STDOUT)
            print(f'Firmware host harness {name}: PASS', flush=True)
    # Stage on the Linux filesystem so Windows mount permissions do not obscure unit checks.
    with tempfile.TemporaryDirectory(prefix='optic-coyote-units-') as temporary:
        units = []
        for name in ('camera', 'reverse'):
            source = ROOT / 'packaging' / f'optic-coyote-{name}.service'
            target = Path(temporary) / source.name
            target.write_text(source.read_text())
            target.chmod(0o644)
            units.append(str(target))
        subprocess.run(['systemd-analyze', 'verify', *units], check=True)
    print('Maintainer shell syntax and systemd unit verification: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
