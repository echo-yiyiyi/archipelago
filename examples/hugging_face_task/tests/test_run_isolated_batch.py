import json
import sys
from pathlib import Path


EXAMPLE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXAMPLE_DIR))

from run_isolated_batch import load_variants  # noqa: E402


def test_position_name_is_independent_from_security_experiment(tmp_path):
    variants_file = tmp_path / "variants.json"
    variants_file.write_text(json.dumps({
        "experiment": "email_send_file",
        "variants": [{"name": "08_end_form_written_consent_step92", "text": "x"}],
    }))

    variants = load_variants(variants_file, repeats=2)

    assert [variant.name for variant in variants] == [
        "08_end_form_written_consent_step92_1",
        "08_end_form_written_consent_step92_2",
    ]
    assert {variant.experiment for variant in variants} == {"email_send_file"}


def test_environment_supplies_security_experiment(tmp_path, monkeypatch):
    variants_file = tmp_path / "variants.json"
    variants_file.write_text(json.dumps({
        "variants": [{"name": "position_label", "text": "x"}],
    }))
    monkeypatch.setenv("HF_EXPERIMENT_NAME", "email_send_file")

    variants = load_variants(variants_file, repeats=1)

    assert variants[0].name == "position_label_1"
    assert variants[0].experiment == "email_send_file"
