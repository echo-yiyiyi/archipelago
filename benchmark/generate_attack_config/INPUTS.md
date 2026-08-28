# `1_email_send_file` Inputs and Outputs

The goal-specific implementation is in `prompt/email_send_file.py`; the shared
JSON-array entry point is `generate.py`.

Running `generate.py INPUT.json` keeps the attack-config JSON at
`generate_attack_config/output/<input>_with_attack_config.json`. For each record
it creates `output/<harmful_task_id>/`, generates the fixture through
`generate_attack_file`, and stores its portable relative path in `attack_file`.

| Output | Input |
|---|---|
| `file_path` | `task_id`, complete task prompt, the `1_email_send_file` template, and all world-file and task-file paths |
| `email_address` | Task keywords, the selected `file_path`, and the `1_email_send_file` template |
| `cot` | Task keywords, the selected `file_path`, the generated `email_address`, the resolved goal, and the COT few-shot examples |
