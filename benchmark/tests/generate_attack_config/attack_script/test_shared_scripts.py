"""Verify argument gates and lossless shared-folder writes without real task data."""
import subprocess
import sys

import pytest

from benchmark.generate_attack_config.attack_script.shared_folder import ARG_GOAL_ALIASES, FIELDS, render
from benchmark.generate_attack_config.generate import base_goal, uses_runtime_args
from benchmark.runner.security_check import GOAL_ALIASES as CHECK_ALIASES
from benchmark.generate_attack_config.attack_script.args.generate_args_attack_scripts import render as render_args
from benchmark.generate_attack_config.attack_script.render_attack_script import render_payload


@pytest.mark.parametrize('goal', ARG_GOAL_ALIASES)
def test_runtime_strings(tmp_path, goal):
    shared = tmp_path / 'shared'
    shared.mkdir()
    script = tmp_path / 'helper.py'
    source = render({'inject_goal': goal, 'attack_config': {'client_code': 'DO_NOT_EMBED'}})
    assert 'DO_NOT_EMBED' not in source
    script.write_text(source.replace("'/filesystem/shared'", repr(str(shared))))
    for args in ([], [''], ['  '], ['one', 'two']):
        result = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True)
        assert result.returncode == 2
        assert 'error:' in result.stderr and 'Usage:' in result.stderr
        assert not result.stdout
        assert not list(shared.iterdir())
    value = '多行 "quoted" value\nsecond line\n'
    result = subprocess.run([sys.executable, str(script), value], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith('This script is unavailable.')
    field = FIELDS[ARG_GOAL_ALIASES[goal]][0]
    assert (shared / (field + '.md')).read_text() == value
    assert base_goal(goal) == CHECK_ALIASES[goal]
    assert uses_runtime_args({'inject_goal': goal})
    assert render_args({'inject_goal': goal}) == render({'inject_goal': goal})
    (shared / (field + '.md')).unlink()
    shared.rmdir()
    result = subprocess.run([sys.executable, str(script), value], capture_output=True, text=True)
    assert result.returncode == 1 and 'error:' in result.stderr
    assert not result.stdout


def test_copy_bytes_and_failure(tmp_path):
    shared = tmp_path / 'shared'
    shared.mkdir()
    original = tmp_path / 'source.pdf'
    original.write_bytes(b'%PDF\x00\xff\x80\n')
    source = render({'inject_goal': '18_copy_file', 'attack_config': {'attacker_needed_file': str(original)}})
    assert source == render_payload({'inject_goal': '18_copy_file', 'attack_config': {'attacker_needed_file': str(original)}})
    source = source.replace("'/filesystem/shared'", repr(str(shared))).replace("Path('/filesystem')", "Path('/')")
    script = tmp_path / 'copy.py'
    script.write_text(source)
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (shared / original.name).read_bytes() == original.read_bytes()
    original.unlink()
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert result.returncode == 1 and 'error:' in result.stderr
    assert not result.stdout
