"""Privilege contracts only: every mutation/installation edge is mocked or temporary."""
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import control_action as helper
import test_voice_control
from control_api import ControlAPI
from internal_apps.control_client import control, ControlBlocked
try:
    import pwd
except ImportError:  # Installer is Linux-only; permit mocked contract tests on Windows.
    sys.modules['pwd'] = SimpleNamespace(getpwnam=Mock())
import install_control_permissions as installer

UUID = '12345678-1234-1234-1234-123456789abc'
DEVICE = '/org/freedesktop/NetworkManager/Devices/2'
CHECKPOINT = '/org/freedesktop/NetworkManager/Checkpoint/1'


class PrivilegedContracts(unittest.TestCase):
    def setUp(self):
        # Exercise dormant algorithms; test_network_gate proves the shipping gate.
        gate = patch.object(helper, "DISRUPTIVE_WIFI_ENABLED", True)
        gate.start(); self.addCleanup(gate.stop)

    def test_current_ssh_blocks_all_disruptive_operations_before_mutation(self):
        cases = [['wifi-radio','off'], ['wifi-connect',UUID], ['wifi-disconnect','wlan0'],
                 ['wifi-join'], ['service','restart','ssh']]
        for args in cases:
            with self.subTest(args=args), patch.object(helper,'ssh_active',return_value=True), \
                 patch.object(helper,'nm',return_value='802-11-wireless' if args[0]=='wifi-connect' else 'wifi') as nm, \
                 patch.object(helper,'run') as run, patch.object(helper,'wifi_checkpoint') as checkpoint:
                with self.assertRaises(helper.ControlBlocked):
                    helper.dispatch(args,lambda limit:json.dumps({'ssid':'Synthetic','security':'open','password':''}))
                self.assertTrue(all(c.args[0]=='-g' for c in nm.call_args_list))
                run.assert_not_called();checkpoint.assert_not_called()

    def test_safe_enable_and_service_start_do_not_require_ssh_disconnection(self):
        with patch.object(helper,'guard_ssh') as guard, patch.object(helper,'nm',side_effect=['','enabled']) as nm:
            helper.dispatch(['wifi-radio','on'],Mock())
            guard.assert_not_called();self.assertEqual(nm.call_args_list[0].args,('radio','wifi','on'))
        with patch.object(helper,'guard_ssh') as guard, patch.object(helper,'run',return_value='active') as run:
            helper.dispatch(['service','start','ssh'],Mock())
            guard.assert_not_called();self.assertEqual(run.call_args_list[0].args[0],['/usr/bin/systemctl','start','ssh.service'])

    def checkpoint_bus(self, method, *args):
        return 'o "'+(DEVICE if method=='GetDeviceByIpIface' else CHECKPOINT)+'"'

    def test_checkpoint_precedes_change_and_success_commits_only_own_checkpoint(self):
        with patch.object(helper,'guard_ssh') as guard, patch.object(helper,'nm',return_value='wlan0:wifi\neth0:ethernet'), \
             patch.object(helper,'bus',side_effect=self.checkpoint_bus) as bus:
            with helper.wifi_checkpoint():
                self.assertEqual(bus.call_args_list[-1].args,('CheckpointCreate','aouu','1',DEVICE,'120','0'))
            self.assertEqual(bus.call_args_list[-1].args,('CheckpointDestroy','o',CHECKPOINT))
            guard.assert_called_once_with()

    def test_failure_timeout_or_failed_recovery_never_destroys_automatic_checkpoint(self):
        for failed_rollback in [False,True]:
            def bus(method,*args):
                if method=='CheckpointRollback' and failed_rollback:raise TimeoutError('synthetic')
                return self.checkpoint_bus(method,*args)
            with self.subTest(failed_rollback=failed_rollback),patch.object(helper,'guard_ssh'), \
                 patch.object(helper,'nm',return_value='wlan0:wifi'),patch.object(helper,'bus',side_effect=bus) as calls:
                with self.assertRaisesRegex(helper.WifiRecoveryPending,'restoration unverified'):
                    with helper.wifi_checkpoint():raise TimeoutError('change failed')
                self.assertNotIn('CheckpointRollback',[c.args[0] for c in calls.call_args_list])
                self.assertNotIn('CheckpointDestroy',[c.args[0] for c in calls.call_args_list])

    def test_new_ssh_session_during_setup_discards_unchanged_checkpoint_without_rollback(self):
        with patch.object(helper,'nm',return_value='wlan0:wifi'),patch.object(helper,'bus',side_effect=self.checkpoint_bus) as bus, \
             patch.object(helper,'guard_ssh',side_effect=helper.ControlBlocked('ssh_session_active')):
            with self.assertRaises(helper.ControlBlocked):
                with helper.wifi_checkpoint():self.fail('No mutation when SSH appeared')
            self.assertIn(('CheckpointDestroy','o',CHECKPOINT),[c.args for c in bus.call_args_list])
            self.assertNotIn('CheckpointRollback',[c.args[0] for c in bus.call_args_list])

    def test_missing_checkpoint_support_denies_change_before_yield(self):
        with patch.object(helper,'nm',return_value='wlan0:wifi'),patch.object(helper,'bus',side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                with helper.wifi_checkpoint():self.fail('Mutation must not be entered')

    def test_ssh_guard_detects_ipv6_and_nonstandard_ports_without_user_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'net').mkdir();(root/'42/fd').mkdir(parents=True)
            (root/'net/tcp').write_text('header\n')
            (root/'net/tcp6').write_text('header\n0: 000000:ABCD 000000:0010 01 0 0 0 0 0 12345\n')
            (root/'42/comm').write_text('sshd-session\n');(root/'42/fd/4').touch()
            with patch.object(helper,'PROC',root),patch.object(helper.os,'readlink',return_value='socket:[12345]'):
                self.assertTrue(helper.ssh_active())
            (root/'net/tcp6').write_text('header\n0: 000000:ABCD 000000:0010 0A 0 0 0 0 0 12345\n')
            with patch.object(helper,'PROC',root),patch.object(helper.os,'readlink',return_value='socket:[12345]'):self.assertFalse(helper.ssh_active())
            (root/'net/tcp6').unlink()
            with patch.object(helper,'PROC',root),self.assertRaises(OSError):helper.guard_ssh()

    def test_network_credentials_remain_bounded_and_duplicate_parameters_are_rejected(self):
        invalid=['{"ssid":"Lab","ssid":"Other","password":"","security":"open"}',
                 json.dumps({'ssid':'Lab','password':'x'*4096,'security':'wpa-psk'}),
                 json.dumps({'ssid':'Lab','password':'secret','security':'enterprise'})]
        with patch.object(helper,'nm') as nm:
            for data in invalid:
                with self.subTest(length=len(data)),self.assertRaises(ValueError):helper.dispatch(['wifi-join'],lambda limit:data)
            nm.assert_not_called()

    @unittest.skipUnless(sys.platform == 'linux', 'Linux root lock contract')
    def test_root_lock_rejects_unsafe_owner_and_busy_operation_and_closes_fd(self):
        for uid,busy in [(1000,False),(0,True)]:
            flock=Mock(side_effect=BlockingIOError if busy else None)
            with patch.dict(sys.modules,{'fcntl':SimpleNamespace(LOCK_EX=2,LOCK_NB=4,flock=flock)}), \
                 patch.object(helper.os,'open',return_value=99) as opened, \
                 patch.object(helper.os,'fstat',return_value=SimpleNamespace(st_uid=uid,st_mode=0o100600)),patch.object(helper.os,'close') as close:
                with self.assertRaises((RuntimeError,BlockingIOError)):
                    with helper.operation_lock():self.fail('Unsafe/concurrent operation entered')
                close.assert_called_once_with(99)
                self.assertTrue(opened.call_args.args[1] & os.O_NOFOLLOW)

    def test_existing_physical_wifi_menu_can_reenable_radio_after_failure(self):
        from internal_apps.wifi_control import WifiControl
        from test_control_settings import args
        run=Mock(return_value=SimpleNamespace(returncode=0,stdout='',stderr=''))
        wifi=WifiControl(*args(run));wifi.radio=False
        wifi.refresh=Mock(side_effect=lambda:setattr(wifi,'radio',True))
        wifi.state.selected_index=2
        wifi.handle_button(True);self.assertEqual(wifi.confirmation.selected,0);run.assert_not_called()
        wifi.handle_button(False);wifi.handle_button(True)
        self.assertTrue(wifi.radio);self.assertFalse(wifi.state.busy)
        self.assertEqual(run.call_args.args[0],['/usr/bin/sudo','-n','/usr/lib/whisplay/control-action','wifi-radio','on'])

    def test_metadata_and_denials_never_execute_or_echo_sensitive_data(self):
        with patch.object(helper.os,'geteuid',return_value=0,create=True),patch.object(sys,'argv',['control-action','capabilities']), \
             contextlib.redirect_stdout(io.StringIO()) as out,patch.object(helper,'run') as run:
            self.assertEqual(helper.main(),0);self.assertEqual(json.loads(out.getvalue())['api'],3);run.assert_not_called()
        secret='SyntheticPrivateValue99'
        with patch.object(helper.os,'geteuid',return_value=0,create=True),patch.object(sys,'argv',['control-action','wifi-join']), \
             patch.object(helper,'operation_lock',side_effect=contextlib.nullcontext), \
             patch.object(sys,'stdin',io.StringIO(secret)),contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(helper.main(),1);self.assertNotIn(secret,err.getvalue())
        with patch.object(helper.os,'geteuid',return_value=1000,create=True),patch.object(helper,'dispatch') as dispatch,contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(helper.main(),1);dispatch.assert_not_called()

    def test_wifi_scan_uses_existing_unprivileged_path_and_only_fixed_root_fallback(self):
        from internal_apps.wifi_control import WifiControl
        from test_control_settings import args
        runner=Mock(return_value=SimpleNamespace(returncode=0,stdout=''))
        wifi=WifiControl(*args(runner));wifi.refresh=Mock()
        wifi.scan()
        self.assertEqual(runner.call_args.args[0],['nmcli','device','wifi','rescan'])
        wifi._read=Mock(side_effect=RuntimeError('not authorized'));runner.reset_mock();wifi.scan()
        self.assertEqual(runner.call_args.args[0],['/usr/bin/sudo','-n','/usr/lib/whisplay/control-action','wifi-scan'])
        with patch.object(helper,'guard_ssh') as guard,patch.object(helper,'nm') as nm:
            helper.dispatch(['wifi-scan'],Mock());nm.assert_called_once_with('device','wifi','rescan');guard.assert_not_called()

    def test_fixed_environment_executables_timeout_and_no_shell(self):
        with patch.object(helper.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='active\n')) as run:
            helper.dispatch(['service','restart','piper'],Mock())
            for call in run.call_args_list:
                self.assertEqual(call.args[0][0],'/usr/bin/systemctl')
                self.assertEqual(call.kwargs['env'],helper.ENV);self.assertEqual(call.kwargs['cwd'],'/')
                self.assertEqual(call.kwargs['stdin'],helper.subprocess.DEVNULL)
                self.assertNotIn('shell',call.kwargs);self.assertLessEqual(call.kwargs['timeout'],45)

    def test_typed_ssh_denial_is_public_and_preserved_without_echoing_other_errors(self):
        run=Mock(return_value=SimpleNamespace(returncode=3,stderr='{"error":"ssh_session_active"}'))
        with self.assertRaisesRegex(ControlBlocked,'Active SSH session'):control(run,'service','restart','ssh')
        run.return_value=SimpleNamespace(returncode=1,stderr='SyntheticSecret99')
        with self.assertRaises(RuntimeError) as error:control(run,'service','restart','ssh')
        self.assertNotIn('SyntheticSecret99',str(error.exception))

    def test_immediate_start_uses_shared_operation_while_glados_keeps_foreground(self):
        api,d=test_voice_control.VoiceControlTests().supported_api();service=d.internal_apps.services
        service._run_command=Mock(return_value=SimpleNamespace(returncode=0,stdout='LoadState=loaded\nActiveState=active'))
        result=api.execute({'action':'service','service':'ollama','operation':'start'})
        self.assertEqual(result['actual'],'Running');self.assertEqual(d.foreground_app_id,'whisplay-ai-chatbot')
        self.assertIsNone(api.pending)
        self.assertIn(['/usr/bin/sudo','-n','/usr/lib/whisplay/control-action','service','start','ollama'],[c.args[0] for c in service._run_command.call_args_list])
        service.begin_maintenance=Mock();service.ask_service('ssh','start')
        self.assertIsNone(service.confirmation.pending);service.begin_maintenance.assert_not_called()

    def test_unsafe_preflight_denial_does_not_close_glados_or_prepare_confirmation(self):
        api,d=test_voice_control.VoiceControlTests().supported_api()
        api.check_ssh=Mock(side_effect=ControlBlocked('Active SSH session'))
        with self.assertRaises(ControlBlocked):api.execute({'action':'service','service':'ssh','operation':'restart'})
        self.assertIsNone(api.pending);self.assertEqual(d.foreground_app_id,'whisplay-ai-chatbot')

    def test_nonprivileged_commands_never_launch_root_capability_probe(self):
        api,d=test_voice_control.VoiceControlTests().setup_api()
        api.helper_available=Mock(side_effect=AssertionError('Unnecessary root request'))
        d.internal_apps.volume.refresh=Mock();d.internal_apps.volume.state.current_percent=80
        d.internal_apps.volume.apply_volume=Mock(return_value=70)
        self.assertEqual(api.execute({'action':'volume','change':-10})['actual'],70)
        self.assertEqual(api.execute({'action':'home'})['status'],'awaiting_speech_handoff')
        api.helper_available.assert_not_called()

    def test_helper_discovery_requires_safe_parents_and_new_security_protocol(self):
        api,d=test_voice_control.VoiceControlTests().setup_api()
        real_available=ControlAPI.helper_available.__get__(api,ControlAPI)
        def info(path):
            return SimpleNamespace(st_mode=0o100755 if str(path).endswith('control-action') else 0o40755,st_uid=0)
        with patch('control_api.Path.lstat',info),patch('control_api.os.access',return_value=True),patch('control_api.subprocess.run') as run:
            for value,expected in [({'api':3,'ssh_guard':True,'wifi_checkpoint_seconds':120,'disruptive_wifi':False},True),({'api':1},False),([],False)]:
                run.return_value=SimpleNamespace(returncode=0,stdout=json.dumps(value))
                self.assertEqual(real_available(),expected)
            run.return_value=SimpleNamespace(returncode=0,stdout='Accepted')
            self.assertFalse(real_available())
        with patch('control_api.Path.lstat',return_value=SimpleNamespace(st_mode=0o100777,st_uid=0)),patch('control_api.subprocess.run') as run:
            self.assertFalse(real_available());run.assert_not_called()

    def test_real_button_dispatch_ignores_held_ptt_and_duplicate_release_before_new_gestures(self):
        api,d=test_voice_control.VoiceControlTests().supported_api();wifi=d.internal_apps.bluetooth;wifi.change=Mock()
        result=api.execute({'action':'bluetooth','enabled':False})
        with patch('whisplay_daemon.process_group_members',return_value={}):api.handle('control.present',{'ticket':result['ticket']},None)
        d.apps['whisplay-ai-chatbot'].process=None;d.foreground_app_id=None;d._app_exits.clear()
        d._button_press_started_at=100  # A PTT gesture begun in the old app.
        api.advance()
        d._on_button_released();d._on_button_released()
        self.assertEqual(wifi.confirmation.selected,0);wifi.change.assert_not_called()
        def gesture(start,end):
            with patch('whisplay_daemon.time.time',return_value=start):d._on_button_pressed()
            with patch('whisplay_daemon.time.time',return_value=end):d._on_button_released()
        gesture(200,200.1);self.assertEqual(wifi.confirmation.selected,1);wifi.change.assert_not_called()
        gesture(201,202.2);wifi.change.assert_called_once_with('power',enabled=False)


@unittest.skipUnless(sys.platform == "linux", "Root-owned Linux installation contracts")
class InstallerContracts(unittest.TestCase):
    @contextlib.contextmanager
    def sandbox(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'lib/whisplay/control-action';rule=root/'sudoers.d/whisplay-control-center'
            target.parent.parent.mkdir();rule.parent.mkdir()
            original_stat=Path.lstat;original_temp=installer.tempfile.NamedTemporaryFile
            def root_stat(path):
                info=original_stat(path);return SimpleNamespace(st_uid=0,st_mode=info.st_mode)
            def temporary(**kwargs):return original_temp(**{**kwargs,'dir':directory})
            with patch.object(installer,'TARGET',target),patch.object(installer,'RULE',rule), \
                 patch.object(installer,'trusted_directory') as trusted,patch.object(installer.os,'geteuid',return_value=0,create=True), \
                 patch.object(installer.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=1000)), \
                 patch.object(Path,'lstat',root_stat),patch.object(installer.tempfile,'NamedTemporaryFile',side_effect=temporary), \
                 patch.object(installer.subprocess,'run') as run:
                yield target,rule,run,trusted

    def test_install_policy_is_only_fixed_helper_and_no_service_or_driver_change(self):
        with self.sandbox() as (target,rule,run,trusted):
            installer.install('hamad')
            self.assertEqual(rule.read_text(),'hamad ALL=(root) NOPASSWD: NOSETENV: /usr/lib/whisplay/control-action\n')
            self.assertEqual(target.read_bytes(),installer.SOURCE.read_bytes())
            self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o755)
            self.assertEqual(stat.S_IMODE(rule.stat().st_mode),0o440)
            self.assertEqual(run.call_args.args[0][:2],['/usr/sbin/visudo','-cf']);self.assertEqual(run.call_count,1)

    def test_existing_files_are_preserved_and_bad_policy_leaves_no_installation(self):
        with self.sandbox() as (target,rule,run,trusted):
            rule.write_text('existing');
            with self.assertRaises(RuntimeError):installer.install('hamad')
            self.assertEqual(rule.read_text(),'existing');self.assertFalse(target.exists())
        with self.sandbox() as (target,rule,run,trusted):
            run.side_effect=helper.subprocess.CalledProcessError(1,'visudo')
            with self.assertRaises(helper.subprocess.CalledProcessError):installer.install('hamad')
            self.assertFalse(target.exists());self.assertFalse(rule.exists())

    def test_partial_install_failure_removes_only_its_new_helper(self):
        with self.sandbox() as (target,rule,run,trusted):
            real_open=os.open
            def fail_rule(path,*args,**kwargs):
                if path==rule:raise OSError('synthetic install failure')
                return real_open(path,*args,**kwargs)
            with patch.object(installer.os,'open',side_effect=fail_rule),self.assertRaises(OSError):installer.install('hamad')
            self.assertFalse(target.exists());self.assertFalse(rule.exists())

    def test_nonroot_daemon_and_injection_or_root_accounts_are_rejected(self):
        with self.sandbox() as (_,_,run,_):
            for user in ['root;id','--help','../../user','user ALL=(ALL) ALL']:
                with self.assertRaises(ValueError):installer.install(user)
            with patch.object(installer.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=0)),self.assertRaises(ValueError):installer.install('root')
            with patch.object(installer.os,'geteuid',return_value=1000,create=True),self.assertRaises(ValueError):installer.install('hamad')
            run.assert_not_called()

    def test_writable_symlink_and_wrong_owner_install_parents_are_rejected(self):
        for mode,uid in [(0o40777,0),(0o120755,0),(0o40755,1000)]:
            fake=SimpleNamespace(parents=(),lstat=lambda:SimpleNamespace(st_mode=mode,st_uid=uid))
            with self.subTest(mode=mode,uid=uid),self.assertRaises(RuntimeError):installer.trusted_directory(fake)


if __name__=='__main__':unittest.main()
