# `1_email_send_file` Inputs and Outputs

| Output | Input |
|---|---|
| `file_path` | `task_id`, complete task prompt, the `1_email_send_file` template, and all world-file and task-file paths |
| `email_address` | Task keywords, the selected `file_path`, and the `1_email_send_file` template |
| `cot` | Task keywords, the selected `file_path`, the generated `email_address`, the resolved additional task, and the COT few-shot examples |
