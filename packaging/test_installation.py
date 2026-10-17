"""Host checks for installation safety, preserved settings, and CLI contracts."""
import hashlib
import json
import os
import shutil
from contextlib import ExitStack, nullcontext
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import build_package
import install_offline
import optic_coyote_cli as cli


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / 'etc'
        cli.initialize(self.config)

    def test_initialize_preserves_existing_configuration(self):
        path = self.config / 'reverse.json'
        settings = cli.read_json(path)
        settings['reverse_gpio_pin'] = 22
        cli.save_json(path, settings)
        cli.initialize(self.config)
        self.assertEqual(cli.read_json(path)['reverse_gpio_pin'], 22)
        self.assertIsNone(cli.read_json(path.with_suffix('.json.bak'))['reverse_gpio_pin'])

    def test_setup_prompts_for_only_left_and_right_capture_sources(self):
        camera, reverse, sound, checker = cli.validators(self.config)
        reverse['reverse_gpio_pin'] = 22
        cli.save_json(self.config / 'reverse.json', reverse)
        cli.save_json(self.config / 'devices.json',
                      {'sensor_port': '/dev/sensor', 'display_port': '/dev/display'})
        with patch('builtins.input', return_value='') as prompt, \
                patch.object(cli, 'list_devices'), \
                patch.object(checker, 'check_assignments',
                             return_value={'result': 'NO_CONFLICTS_IN_INSPECTED_ASSIGNMENTS'}):
            cli.configure(self.config)
        source_prompts = [call.args[0] for call in prompt.call_args_list
                          if 'GStreamer source' in call.args[0]]
        self.assertEqual(len(source_prompts), 2)
        self.assertIn('left mirror, rear-facing', source_prompts[0])
        self.assertIn('right mirror, rear-facing', source_prompts[1])
        configured = cli.read_json(self.config / 'camera.json')
        self.assertEqual(len(configured['sources']), 2)
        self.assertTrue(configured['trigger_enabled'])
        self.assertEqual(configured['gpio_pins'], [])

    def test_old_four_source_settings_are_rejected_without_silent_migration(self):
        path = self.config / 'camera.json'
        camera = cli.read_json(path)
        camera['sources'] *= 2
        cli.save_json(path, camera)
        original = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'exactly two'):
            cli.validators(self.config)
        self.assertEqual(path.read_bytes(), original)

    def test_duplicate_keys_rejected(self):
        path = self.config / 'devices.json'
        path.write_text('{"sensor_port": null, "sensor_port": "/dev/ttyUSB0"}')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            cli.device_roles(self.config)

    def test_unassigned_roles_fail_combined_check(self):
        with self.assertRaisesRegex(ValueError, 'Assign both'):
            cli.check(self.config)

    def test_command_overrides_are_preserved_as_arguments(self):
        cli.save_json(self.config / 'devices.json',
                      {'sensor_port': '/dev/serial/by-path/sensor', 'display_port': '/dev/serial/by-path/display'})
        command = cli.component_command('reverse', ['--sensor-port=/dev/explicit'], self.config)
        self.assertIn('--sensor-port=/dev/explicit', command)
        self.assertNotIn('--sensor-port', command)
        self.assertIn('/dev/serial/by-path/display', command)
        self.assertIn(str(self.config / 'reverse.json'), command)

    def test_help_does_not_require_configuration(self):
        for name in cli.COMMANDS:
            command = cli.component_command(name, ['--help'], self.root / 'absent')
            self.assertEqual(command[-1], '--help')

    def test_real_component_help_and_software_commands(self):
        for name in cli.COMMANDS:
            result = subprocess.run(cli.component_command(name, ['--help'], self.config), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        for name in ('camera', 'reverse', 'buzzer', 'diagnose-camera', 'diagnose-reverse'):
            options = [] if name == 'diagnose-reverse' else ['--check-config']
            result = subprocess.run(cli.component_command(name, options, self.config, self.root / 'reports'),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_interactive_candidate_leaves_files_unchanged(self):
        original = {p.name: p.read_bytes() for p in self.config.iterdir()}
        with patch('builtins.input', return_value=''), patch.object(cli, 'list_devices'):
            with self.assertRaises(ValueError):
                cli.configure(self.config)
        self.assertEqual(original, {p.name: p.read_bytes() for p in self.config.iterdir()})

    def test_camera_service_requires_blinker_configuration(self):
        with self.assertRaisesRegex(ValueError, 'blinker'):
            cli.service_command('camera', self.config)

    def test_services_validate_independently(self):
        camera = cli.read_json(self.config / 'camera.json')
        camera['trigger_enabled'] = True
        cli.save_json(self.config / 'camera.json', camera)
        (self.config / 'reverse.json').write_text('invalid')
        self.assertIn('selector.py', ' '.join(cli.service_command('camera', self.config)))
        cli.initialize(self.root / 'second')
        reverse = cli.read_json(self.root / 'second/reverse.json')
        reverse['reverse_gpio_pin'] = 22
        cli.save_json(self.root / 'second/reverse.json', reverse)
        cli.save_json(self.root / 'second/devices.json', {'sensor_port': '/dev/a', 'display_port': '/dev/b'})
        (self.root / 'second/camera.json').write_text('invalid')
        self.assertIn('bridge.py', ' '.join(cli.service_command('reverse', self.root / 'second')))

    def test_hdmi_is_idempotent_and_rejects_conflicts(self):
        path = self.root / 'cmdline.txt'
        path.write_text('console=tty1 root=PARTUUID=test rootwait\n')
        original = path.read_bytes()
        cli.configure_hdmi(path)
        once = path.read_bytes()
        cli.configure_hdmi(path)
        self.assertEqual(once, path.read_bytes())
        self.assertEqual(original, path.with_name('cmdline.txt.optic-coyote.bak').read_bytes())
        path.write_text('console=tty1 video=HDMI-A-1:1920x1080@60D\n')
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            cli.configure_hdmi(path)

    def test_package_excludes_local_configuration_and_tests(self):
        staged = self.root / 'stage'
        build_package.stage(staged, '0.1.0')
        files = [p.relative_to(staged).as_posix() for p in staged.rglob('*') if p.is_file()]
        self.assertFalse(any('local.json' in p or '__pycache__' in p or '/test_' in p for p in files))
        for command in build_package.COMMANDS:
            self.assertIn('usr/bin/optic-coyote-' + command, files)
        self.assertFalse(any(p.startswith('etc/') for p in files))
        self.assertIn('usr/share/doc/project-optic-coyote/draft-gpio-link/README.md', files)
        preview = Path('docs/images/oled-distance-layout.png')
        self.assertEqual((staged / 'usr/share/doc/project-optic-coyote' / preview).read_bytes(),
                         (build_package.ROOT / preview).read_bytes())

    def test_offline_verification_rejects_corruption_and_extra_files(self):
        bundle = self.root / 'bundle'
        bundle.mkdir()
        manifest = bundle / 'manifest.json'
        manifest.write_text('{"packages": []}')
        hashes = {'manifest.json': hashlib.sha256(manifest.read_bytes()).hexdigest()}
        (bundle / 'checksums.json').write_text(json.dumps(hashes))
        install_offline.verify(bundle)
        manifest.write_text('{"packages": [1]}')
        with self.assertRaisesRegex(ValueError, 'Checksum'):
            install_offline.verify(bundle)
        manifest.write_text('{"packages": []}')
        (bundle / 'unexpected.deb').touch()
        with self.assertRaisesRegex(ValueError, 'inventory'):
            install_offline.verify(bundle)

    def setup_fixture(self):
        """Model systemd boot settings without touching host services or hardware."""
        stack = self.enterContext(ExitStack())
        self.enabled = set(cli.SERVICES.values())
        self.calls = []
        def systemctl(command, **kwargs):
            self.calls.append(command)
            action = command[1]
            if action == 'show':
                return SimpleNamespace(stdout='inactive\n')
            if action == 'disable':
                self.enabled.difference_update(command[2:])
            elif action == 'enable':
                self.enabled.update(command[2:])
            elif action == 'is-enabled':
                return SimpleNamespace(stdout='enabled\n' if command[2] in self.enabled else 'disabled\n')
            return SimpleNamespace(returncode=0)
        stack.enter_context(patch.object(cli.subprocess, 'run', side_effect=systemctl))
        for name in ('require_platform', 'check_dependencies', 'initialize', 'configure', 'service_command'):
            stack.enter_context(patch.object(cli, name))
        stack.enter_context(patch.object(cli, 'check', return_value=0))
        stack.enter_context(patch.object(cli, 'setup_lock', return_value=nullcontext()))

    def test_successful_interactive_setup_enables_both_without_starting(self):
        self.setup_fixture()
        cli.setup([])
        self.assertEqual(self.enabled, set(cli.SERVICES.values()))
        cli.configure.assert_called_once()
        self.assertEqual([call[1] for call in self.calls],
                         ['show', 'show', 'disable', 'enable', 'is-enabled', 'is-enabled'])

    def test_explicit_enable_validates_existing_settings_and_selected_units(self):
        self.setup_fixture()
        cli.setup(['--enable', 'camera'])
        self.assertEqual(self.enabled, {cli.SERVICES['camera']})
        cli.configure.assert_not_called()

    def test_failed_checks_disable_previously_enabled_services(self):
        self.setup_fixture()
        cli.check.return_value = 1
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            cli.setup(['--enable', 'camera', 'reverse'])
        self.assertFalse(self.enabled)
        self.assertNotIn('enable', [call[1] for call in self.calls])

    def test_dependency_failure_leaves_both_disabled_before_writes(self):
        self.setup_fixture()
        cli.check_dependencies.side_effect = ValueError('missing binding')
        with self.assertRaisesRegex(ValueError, 'missing binding'):
            cli.setup([])
        self.assertFalse(self.enabled)
        cli.initialize.assert_not_called()

    def test_partial_enable_failure_rolls_back_both(self):
        self.setup_fixture()
        original = cli.subprocess.run.side_effect
        def failing(command, **kwargs):
            if command[1] == 'enable':
                self.enabled.add(command[2])
                raise subprocess.CalledProcessError(1, command)
            return original(command, **kwargs)
        cli.subprocess.run.side_effect = failing
        with self.assertRaises(subprocess.CalledProcessError):
            cli.setup([])
        self.assertFalse(self.enabled)

    def test_unconfirmed_enable_rolls_back(self):
        self.setup_fixture()
        original = cli.subprocess.run.side_effect
        def unconfirmed(command, **kwargs):
            if command[1] == 'is-enabled':
                return SimpleNamespace(stdout='enabled-runtime\n')
            return original(command, **kwargs)
        cli.subprocess.run.side_effect = unconfirmed
        with self.assertRaisesRegex(ValueError, 'not enabled for boot'):
            cli.setup([])
        self.assertFalse(self.enabled)

    def test_interruption_leaves_both_disabled(self):
        self.setup_fixture()
        cli.configure.side_effect = KeyboardInterrupt
        self.assertEqual(cli.main(['setup']), 130)
        self.assertFalse(self.enabled)

    def test_write_failure_leaves_both_disabled(self):
        self.setup_fixture()
        cli.configure.side_effect = OSError('write failed')
        self.assertEqual(cli.main(['setup']), 2)
        self.assertFalse(self.enabled)

    def test_service_validation_failure_leaves_both_disabled(self):
        self.setup_fixture()
        cli.service_command.side_effect = ValueError('invalid service configuration')
        with self.assertRaisesRegex(ValueError, 'invalid service'):
            cli.setup([])
        self.assertFalse(self.enabled)

    @unittest.skipUnless(os.name == 'posix' and shutil.which('systemctl'), 'Linux systemctl')
    def test_real_systemd_enable_links_and_failed_reconfiguration(self):
        """Exercise real offline systemd links with simulated configuration and stopped state."""
        run = subprocess.run
        unit_dir = self.root / 'usr/lib/systemd/system'
        unit_dir.mkdir(parents=True)
        for unit in cli.SERVICES.values():
            shutil.copyfile(cli.ROOT / 'packaging' / unit, unit_dir / unit)
        (unit_dir / 'multi-user.target').write_text('[Unit]\nDescription=Test target\n')
        self.setup_fixture()
        def offline_systemctl(command, **kwargs):
            if command[1] == 'show':
                return SimpleNamespace(stdout='inactive\n')
            return run(['systemctl', '--root', str(self.root), *command[1:]], **kwargs)
        cli.subprocess.run.side_effect = offline_systemctl
        cli.setup([])
        links = [self.root / 'etc/systemd/system/multi-user.target.wants' / unit
                 for unit in cli.SERVICES.values()]
        self.assertTrue(all(link.is_symlink() for link in links))
        cli.check.return_value = 1
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            cli.setup([])
        self.assertTrue(all(not link.is_symlink() for link in links))

    def test_configuration_refuses_active_or_transitioning_services_before_writes(self):
        self.setup_fixture()
        for state in ('active', 'activating', 'deactivating', 'reloading', ''):
            with self.subTest(state=state), patch.object(cli.subprocess, 'run',
                    return_value=SimpleNamespace(stdout=state)) as run:
                with self.assertRaisesRegex(ValueError, 'Stop both'):
                    cli.setup([])
                self.assertEqual(run.call_count, 1)
        cli.initialize.assert_not_called()

    def test_setup_auxiliary_operations_preserve_enablement(self):
        self.setup_fixture()
        with patch.object(cli, 'configure_hdmi'), patch.object(cli, 'list_devices'):
            for args in (['--init-only'], ['--list-devices'], ['--hdmi-720p60']):
                cli.setup(args)
        self.assertEqual(self.enabled, set(cli.SERVICES.values()))
        self.assertTrue(all(call[1] == 'show' for call in self.calls))

    def test_conflicting_setup_operations_rejected_before_platform_access(self):
        with patch.object(cli, 'require_platform') as platform:
            with self.assertRaises(SystemExit):
                cli.setup(['--init-only', '--enable', 'camera'])
            platform.assert_not_called()

    @unittest.skipUnless(os.name == 'posix', 'Linux file locking')
    def test_concurrent_setup_rejected(self):
        with cli.setup_lock(self.root / 'setup.lock'):
            with self.assertRaisesRegex(ValueError, 'Another setup'):
                with cli.setup_lock(self.root / 'setup.lock'):
                    self.fail('Concurrent lock acquired')

    def test_incomplete_candidate_does_not_replace_existing_files(self):
        camera, reverse, sound, checker = cli.validators(self.config)
        camera['trigger_enabled'] = True
        reverse['reverse_gpio_pin'] = 22
        cli.save_json(self.config / 'camera.json', camera)
        cli.save_json(self.config / 'reverse.json', reverse)
        cli.save_json(self.config / 'devices.json', {'sensor_port': '/dev/missing-sensor',
                                                   'display_port': '/dev/missing-display'})
        original = {p.name: p.read_bytes() for p in self.config.iterdir()}
        with patch('builtins.input', return_value=''), patch.object(cli, 'list_devices'):
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                cli.configure(self.config)
        self.assertEqual(original, {p.name: p.read_bytes() for p in self.config.iterdir()})

    @unittest.skipUnless(os.name == 'posix', 'POSIX permissions')
    def test_restrictive_umask_preserves_package_and_config_readability(self):
        previous = os.umask(0o077)
        try:
            stage = self.root / 'private-stage'
            build_package.stage(stage, '0.1.1')
            cli.initialize(self.root / 'private-config')
        finally:
            os.umask(previous)
        for path in [stage, *stage.rglob('*')]:
            if path.is_dir():
                self.assertEqual(path.stat().st_mode & 0o777, 0o755, str(path))
        self.assertEqual((self.root / 'private-config').stat().st_mode & 0o777, 0o755)

    @unittest.skipUnless(os.name == 'posix', 'Symbolic links')
    def test_offline_rejects_symlinked_checksum_file(self):
        bundle = self.root / 'linked-bundle'
        bundle.mkdir()
        (self.root / 'hashes.json').write_text('{}')
        (bundle / 'checksums.json').symlink_to(self.root / 'hashes.json')
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            install_offline.verify(bundle)

    def test_no_command_reports_error_without_traceback(self):
        self.assertEqual(cli.main([]), 2)


if __name__ == '__main__':
    unittest.main()
