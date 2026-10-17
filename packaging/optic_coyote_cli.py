#!/usr/bin/python3
"""Installed command dispatch and explicit Pi configuration administration.

Component validators own their configuration rules. This module supplies
installed paths and device roles without changing component runtime behavior.
"""
import argparse
from contextlib import contextmanager
import glob
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path('/etc/project-optic-coyote')
STATE = Path.home() / '.local/state/project-optic-coyote'
SERVICES = {name: f'optic-coyote-{name}.service' for name in ('camera', 'reverse')}
TEMPLATES = {
    'camera.json': 'rpi-ahd-selector/config.json',
    'reverse.json': 'rpi-oled-bridge/reverse.json',
    'buzzer.json': 'rpi-buzzer/buzzer.json',
    'camera-diagnostic.json': 'rpi-ahd-selector/diagnostic.json',
    'reverse-diagnostic.json': 'rpi-oled-bridge/reverse-diagnostic.json',
}
COMMANDS = {
    'camera': ('rpi-ahd-selector/selector.py', '--config', 'camera.json'),
    'control': ('rpi-ahd-selector/control.py', None, None),
    'reverse': ('rpi-oled-bridge/bridge.py', '--reverse-config', 'reverse.json'),
    'buzzer': ('rpi-buzzer/buzzer.py', '--config', 'buzzer.json'),
    'diagnose-camera': ('rpi-ahd-selector/diagnose_adapter.py', '--config', 'camera-diagnostic.json'),
    'diagnose-reverse': ('rpi-oled-bridge/diagnose_reverse.py', '--config', 'reverse-diagnostic.json'),
}


def read_json(path):
    """Read an object while rejecting duplicate keys and malformed configuration."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate key: {key}')
            result[key] = value
        return result
    value = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError(f'{path} must contain a JSON object')
    return value


def save_json(path, value):
    """Atomically replace a configuration file, retaining the previous version."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + '.bak'))
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + '.')
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def initialize(directory=CONFIG):
    """Create missing local files; package upgrades never replace local settings."""
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o755)
    for name, source in TEMPLATES.items():
        if not (directory / name).exists():
            save_json(directory / name, read_json(ROOT / source))
    if not (directory / 'devices.json').exists():
        save_json(directory / 'devices.json', {'sensor_port': None, 'display_port': None})


def device_roles(directory=CONFIG):
    """Return explicit serial roles; null values remain unassigned."""
    roles = read_json(directory / 'devices.json')
    if set(roles) != {'sensor_port', 'display_port'}:
        raise ValueError('devices.json requires only sensor_port and display_port')
    for value in roles.values():
        if value is not None and (not isinstance(value, str) or not value.startswith('/dev/')
                                  or '\x00' in value or any(char.isspace() for char in value)):
            raise ValueError('Serial roles must be absolute /dev/ paths without whitespace')
    return roles


def default_option(args, name, value):
    """Supply a default only when the command line has not provided the option."""
    if value is not None and not any(arg == name or arg.startswith(name + '=') for arg in args):
        args.extend([name, str(value)])


def component_command(name, args, directory=CONFIG, state=STATE):
    """Build an argument vector without shell interpolation or device access."""
    script, option, filename = COMMANDS[name]
    args = list(args)
    if '--help' in args or '-h' in args:
        return [sys.executable, '-B', str(ROOT / script), *args]
    if option:
        default_option(args, option, directory / filename)
    if name in ('reverse', 'diagnose-reverse'):
        default_option(args, '--reverse-config', directory / 'reverse.json')
        if '--list-ports' not in args and '--check-config' not in args:
            for key, value in device_roles(directory).items():
                default_option(args, '--' + key.replace('_', '-'), value)
    if name.startswith('diagnose-'):
        default_option(args, '--report-dir', state / name)
    return [sys.executable, '-B', str(ROOT / script), *args]


def validators(directory=CONFIG):
    """Load existing validators using the installed component directory layout."""
    sys.path[:0] = [str(ROOT / part) for part in
                    ('rpi-ahd-selector', 'rpi-oled-bridge', 'rpi-buzzer', 'tools')]
    import selector
    import reverse_control
    import buzzer
    import check_trigger_setup
    camera = selector.validate(read_json(directory / 'camera.json'))
    reverse = reverse_control.load_config(directory / 'reverse.json')
    sound = buzzer.load_config(directory / 'buzzer.json')
    return camera, reverse, sound, check_trigger_setup


def check(directory=CONFIG):
    """Check configuration and device metadata without opening hardware."""
    camera, reverse, sound, checker = validators(directory)
    roles = device_roles(directory)
    if not all(roles.values()):
        raise ValueError('Assign both serial roles in devices.json before the combined check')
    report = checker.check_assignments(camera, reverse, roles['sensor_port'], roles['display_port'], sound)
    print(json.dumps(report, indent=2))
    return 1 if report['result'] == 'INCOMPLETE' else 0


def require_platform():
    """Reject administrative changes outside Raspberry Pi 5 / Trixie arm64."""
    if os.geteuid() != 0:
        raise ValueError('Run setup through sudo')
    release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines()
                   if '=' in line and not line.startswith('#'))
    if release.get('VERSION_CODENAME', '').strip('"\'') != 'trixie':
        raise ValueError('Setup requires Raspberry Pi OS Trixie')
    architecture = subprocess.check_output(['dpkg', '--print-architecture'], text=True).strip()
    model = Path('/proc/device-tree/model').read_text().rstrip('\x00')
    if architecture != 'arm64' or not model.startswith('Raspberry Pi 5'):
        raise ValueError('Setup requires a Raspberry Pi 5 with an arm64 OS')


def check_dependencies():
    """Check installed Python bindings and GStreamer elements without opening devices."""
    subprocess.run([sys.executable, '-c', 'import serial, gpiozero, lgpio, gi'], check=True)
    for element in ('v4l2src', 'jpegdec', 'kmssink'):
        subprocess.run(['gst-inspect-1.0', element], check=True, stdout=subprocess.DEVNULL)


def list_devices():
    """List stable device paths; enumeration does not assign physical roles."""
    for pattern in ('/dev/v4l/by-id/*', '/dev/v4l/by-path/*',
                    '/dev/serial/by-id/*', '/dev/serial/by-path/*'):
        for path in sorted(glob.glob(pattern)):
            print(f'{path} -> {os.path.realpath(path)}')


def prompt_value(label, current, convert=str):
    """Retain a current value on empty input; otherwise parse the supplied value."""
    answer = input(f'{label} [{current if current is not None else "unassigned"}]: ').strip()
    return convert(answer) if answer else current


def configure(directory=CONFIG):
    """Collect assignments and validate the complete candidate before writing it."""
    camera, reverse, sound, checker = validators(directory)
    roles = device_roles(directory)
    list_devices()
    print('Identify each device physically. Empty input retains the displayed value.')
    for key in roles:
        roles[key] = prompt_value(key, roles[key])
    reverse['reverse_gpio_pin'] = prompt_value('Reverse BCM pin', reverse['reverse_gpio_pin'], int)
    for key in ('trigger_left_pin', 'trigger_right_pin', 'trigger_left_camera', 'trigger_right_camera'):
        camera[key] = prompt_value(key, camera[key], int)
    for index, source in enumerate(camera['sources']):
        side = "left" if index + 1 == camera["trigger_left_camera"] else "right"
        prompt = f"Camera {index + 1} ({side} mirror, rear-facing) GStreamer source"
        camera["sources"][index] = prompt_value(prompt, source)
    camera['trigger_enabled'] = True
    # The installed service uses blinker control; manual transports remain separate.
    camera['gpio_pins'] = []
    with tempfile.TemporaryDirectory() as temporary:
        candidate = Path(temporary)
        for name, value in (('camera.json', camera), ('reverse.json', reverse),
                            ('buzzer.json', sound), ('devices.json', roles)):
            save_json(candidate / name, value)
        validated_camera, validated_reverse, validated_sound, _ = validators(candidate)
        device_roles(candidate)
        if not all(roles.values()):
            raise ValueError('Both sensor and display roles must be assigned')
        report = checker.check_assignments(validated_camera, validated_reverse,
                                          roles['sensor_port'], roles['display_port'], validated_sound)
    print(json.dumps(report, indent=2))
    if report['result'] == 'INCOMPLETE':
        raise ValueError('Resolve incomplete device checks before saving configuration')
    for name, value in (('camera.json', camera), ('reverse.json', reverse), ('devices.json', roles)):
        save_json(directory / name, value)
    print('Validated configuration saved.')


def configure_hdmi(path=Path('/boot/firmware/cmdline.txt')):
    """Append the 720p60 mode once; preserve unrelated arguments and reject conflicts."""
    text = path.read_text()
    if len(text.strip().splitlines()) != 1:
        raise ValueError('cmdline.txt must contain one nonempty line')
    mode = 'video=HDMI-A-1:1280x720@60D'
    existing = [item for item in text.split() if item.startswith('video=HDMI-A-1:')]
    if existing and existing != [mode]:
        raise ValueError('Conflicting HDMI-A-1 setting; edit cmdline.txt explicitly')
    if not existing:
        shutil.copy2(path, path.with_name('cmdline.txt.optic-coyote.bak'))
        path.write_text(text.rstrip() + ' ' + mode + '\n')
    print('HDMI mode configured. Reboot before display testing.')


def service_command(name, directory=CONFIG):
    """Validate only this service at startup to preserve independent recovery."""
    if name == 'camera':
        sys.path.insert(0, str(ROOT / 'rpi-ahd-selector'))
        import selector
        camera = selector.validate(read_json(directory / 'camera.json'))
        if not camera['trigger_enabled'] or camera['gpio_pins']:
            raise ValueError('Camera service requires configured blinker mode')
    else:
        sys.path.insert(0, str(ROOT / 'rpi-oled-bridge'))
        import reverse_control
        reverse = reverse_control.load_config(directory / 'reverse.json')
        if reverse['reverse_gpio_pin'] is None or not all(device_roles(directory).values()):
            raise ValueError('Reverse service requires GPIO and serial role assignments')
    return component_command(name, [], directory)


@contextmanager
def setup_lock(path=Path('/run/lock/optic-coyote-setup.lock')):
    """Serialize administrative setup so concurrent runs cannot enable stale settings."""
    import fcntl
    with path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('Another setup operation is running') from error
        yield


def require_stopped():
    """Reject configuration changes while either service is running or transitioning."""
    for service in SERVICES.values():
        result = subprocess.run(['systemctl', 'show', '--property=ActiveState', '--value', service],
                                check=True, capture_output=True, text=True)
        if result.stdout.strip() not in ('inactive', 'failed'):
            raise ValueError('Stop both services before changing configuration or enablement')


def configure_services(names, interactive=True, directory=CONFIG):
    """Enable validated services for boot; any failed operation leaves both disabled.

    Existing processes must already be stopped. Disablement precedes dependency
    checks and writes. Rollback also covers interruption and partial enablement.
    """
    require_stopped()
    units = list(SERVICES.values())
    try:
        subprocess.run(['systemctl', 'disable', *units], check=True)
        check_dependencies()
        initialize(directory)
        if interactive:
            configure(directory)
        if check(directory) != 0:
            raise ValueError('Resolve incomplete device checks before enabling services')
        for name in names:
            service_command(name, directory)
        selected = [SERVICES[name] for name in names]
        subprocess.run(['systemctl', 'enable', *selected], check=True)
        for service in selected:
            result = subprocess.run(['systemctl', 'is-enabled', service], check=True,
                                    capture_output=True, text=True)
            if result.stdout.strip() != 'enabled':
                raise ValueError(f'Service was not enabled for boot: {service}')
    except BaseException:
        # A rollback failure must be visible; disabled state cannot then be guaranteed.
        try:
            subprocess.run(['systemctl', 'disable', *units], check=True)
        except (OSError, subprocess.CalledProcessError) as error:
            print(f'Unable to disable both services during rollback: {error}', file=sys.stderr)
            raise
        raise
    print('Enabled for boot: ' + ', '.join(names) + '. Services have not been started.')


def setup(argv):
    """Configure the Pi and automatically enable both services for boot without starting them."""
    parser = argparse.ArgumentParser(description=setup.__doc__)
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument('--init-only', action='store_true', help='create missing configuration only; preserve enablement')
    operation.add_argument('--list-devices', action='store_true', help='list stable paths without opening devices')
    operation.add_argument('--hdmi-720p60', action='store_true', help='set HDMI0 boot mode; preserve enablement')
    operation.add_argument('--enable', nargs='+', choices=tuple(SERVICES),
                           help='validate existing settings and enable only selected services; does not start them')
    args = parser.parse_args(argv)
    if args.list_devices:
        list_devices()
        return 0
    require_platform()
    with setup_lock():
        if args.init_only:
            initialize()
        elif args.hdmi_720p60:
            require_stopped()
            configure_hdmi()
        else:
            configure_services(tuple(dict.fromkeys(args.enable or SERVICES)), interactive=not args.enable)
    return 0


def main(argv=None):
    """Dispatch installed commands; exec preserves signals and component exit status."""
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if not args:
            raise ValueError('A command is required')
        name = args.pop(0)
        if name == 'initialize':
            initialize()
            return 0
        if name == 'setup':
            return setup(args)
        if name == 'check':
            parser = argparse.ArgumentParser(description=check.__doc__)
            parser.add_argument('--config-dir', type=Path, default=CONFIG)
            parsed = parser.parse_args(args)
            return check(parsed.config_dir)
        if name == 'service':
            if len(args) != 1 or args[0] not in SERVICES:
                raise ValueError('service requires camera or reverse')
            command = service_command(args[0])
        else:
            command = component_command(name, args)
        os.execv(command[0], command)
    except (OSError, ValueError, KeyError, EOFError, subprocess.CalledProcessError) as error:
        print(f'Optic Coyote: {error}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('Optic Coyote: setup interrupted', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
