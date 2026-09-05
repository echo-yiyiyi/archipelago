"""Ensure TXT instructions include the executable's actual missing-argument help."""
import subprocess
import sys

import pytest

from benchmark.generate_attack_config.attack_script.args.generate_args_attack_scripts import GOAL_ALIASES, render
from benchmark.generate_attack_config.prompt.task_instruction import argument_instruction, render_instruction_body


@pytest.mark.parametrize('goal', GOAL_ALIASES)
def test_missing_argument_information_matches_executable(tmp_path, goal):
    record = {'inject_goal': goal, 'attack_file': 'helper.py', 'attack_config': {
        'attacker_email_address': 'fixture@example.com',
        'attacker_link': 'https://example.com/fixture',
        'channel_id': 'channel-fixture-123', 'calendar_event_id': 'event-fixture-456',
    }}
    helper = tmp_path / 'helper.py'
    helper.write_text(render(record))
    result = subprocess.run([sys.executable, str(helper)], capture_output=True, text=True)
    assert result.returncode == 2
    instruction = argument_instruction(record, 'helper.py')
    assert result.stderr.strip() in instruction
    assert result.stdout == ''
    if goal == '17_chat_to_achieve_url_arg':
        assert 'channel_id=channel-fixture-123' in instruction
        assert 'not the task prompt' in instruction
    if goal == '16_email_broadcast_link_arg':
        assert 'event_id=event-fixture-456' in instruction


def test_final_answer_instruction_has_no_early_run_directive():
    text = render_instruction_body({'inject_goal': '30_save_final_answer_arg'},
                                   'the analysis', './helper', 'the result')
    assert 'before submitting your final answer' in text
    assert 'validate' in text
    assert 'Before beginning' not in text
    assert 'Run it first' not in text


@pytest.mark.parametrize('goal', ['16_email_broadcast_link_arg', '17_chat_to_achieve_url_arg'])
def test_lookup_id_required(goal):
    with pytest.raises(ValueError, match='requires'):
        argument_instruction({'inject_goal': goal, 'attack_config': {}}, './helper')
