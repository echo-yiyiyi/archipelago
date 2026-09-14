"""Exercise both help flags through PY, PYC and ELF without running actions."""
import base64
import py_compile
import subprocess
import sys

import pytest

from benchmark.generate_attack_config.attack_script.shared_folder import render as shared
from benchmark.generate_attack_config.attack_script.render_attack_script import render_payload
from benchmark.generate_attack_config.attack_script.args.generate_args_attack_scripts import render, C_TEMPLATE, _c_chunks
from benchmark.generate_attack_config.watcher.script_generate import recover_source


def sources():
    from benchmark.generate_attack_config.attack_script.render_attack_script import GOAL_BODIES
    from benchmark.generate_attack_config.attack_script.args.generate_args_attack_scripts import GOAL_ALIASES
    config = {'attacker_email_address': 'review@example.test', 'attacker_link': 'https://example.test/',
              'attacker_needed_file': '/filesystem/input.txt', 'channel_id': 'test-channel',
              'calendar_event_id': 'test-event', 'event_start': '20260901T150000Z',
              'event_end': '20260901T160000Z', 'event_summary': 'Example meeting',
              'otp_mail_id': '<example@benchmark.local>'}
    sources = {}
    for goal in [*GOAL_BODIES, '18_copy_file']:
        sources['direct_' + goal] = render_payload({'inject_goal': goal, 'attack_config': config})
    for goal in GOAL_ALIASES:
        record = {'inject_goal': goal, 'attack_file': 'helper.py', 'attack_config': config}
        sources['args_' + goal] = render(record)
        sources['recovery_' + goal] = recover_source(record, '/nonexistent-help-test.sock')
    return sources


@pytest.mark.parametrize('kind', list(sources()))
@pytest.mark.parametrize('format', ['py', 'pyc', 'elf'])
def test_both_flags_exit_without_actions(tmp_path, kind, format):
    source = sources()[kind].replace('/filesystem', str(tmp_path / 'filesystem'))
    # Fail explicitly if help reaches a background action or network/session work.
    guard = '''\nimport os

def forbidden(*args, **kwargs):
    raise RuntimeError('help reached an action')
os.fork = forbidden
open_session = forbidden
recovery_request = forbidden
'''
    at = source.rfind('if __name__')
    assert at >= 0
    source = source[:at] + guard + source[at:]
    script = tmp_path / 'helper.py'
    script.write_text(source)
    if format == 'py':
        command = [sys.executable, str(script)]
    elif format == 'pyc':
        bytecode = tmp_path / 'helper.pyc'
        py_compile.compile(str(script), cfile=str(bytecode), doraise=True)
        command = [sys.executable, str(bytecode)]
    else:
        cfile = tmp_path / 'helper.c'
        cfile.write_text(C_TEMPLATE.format(b64_literal=_c_chunks(base64.b64encode(source.encode()).decode())))
        binary = tmp_path / 'helper'
        subprocess.run(['gcc', '-o', str(binary), str(cfile)], check=True, capture_output=True)
        command = [str(binary)]
    outputs = []
    for flag in ('-h', '--help'):
        result = subprocess.run([*command, flag], capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        assert result.stdout or result.stderr
        assert 'This script is unavailable.' not in result.stdout
        assert not (tmp_path / 'filesystem').exists()
        outputs.append((result.stdout, result.stderr))
    assert outputs[0] == outputs[1]


def test_legacy_binary_builder_handles_help_before_payload(tmp_path):
    from benchmark.generate_attack_config.attack_script.build_binaries import C_TEMPLATE as legacy
    cfile = tmp_path / 'legacy.c'
    payload = base64.b64encode(b"raise RuntimeError('help executed payload')").decode()
    cfile.write_text(legacy.format(b64_literal='"'+payload+'"', decoy='DECOY'))
    binary = tmp_path / 'legacy'
    subprocess.run(['gcc', '-o', str(binary), str(cfile)], check=True, capture_output=True)
    for flag in ('-h', '--help'):
        result = subprocess.run([str(binary), flag], capture_output=True, text=True, timeout=15)
        assert result.returncode == 0
        assert result.stdout.startswith('Usage: ')
        assert 'DECOY' not in result.stdout and not result.stderr
