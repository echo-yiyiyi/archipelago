# Attack-config generation folder structure

`generate.py` is the only entry point for the normal attack-config generation
pipeline:

```text
benchmark/generate_attack_config/generate.py
```

It reads one input JSON array and processes every record independently. Each
record selects its own `inject_goal`, `inject_vector`, and `add_user_prompt`.
The output is a JSON file plus one artifact directory per
`harmful_task_id`.

## Generation call chain

```text
input tasks.json
      |
      v
generate_attack_config/generate.py
      |
      +-- inject_goal -> prompt/<goal_generator>.py
      |                    |
      |                    +-- common.py
      |                    +-- cot.py
      |                    +-- task_instruction.py (lure .txt when needed)
      |
      +-- inject_vector -> generate_attack_file/generate.py
      |                         |
      |                         +-- generate_attack_file/api.py
      |                         +-- generate_attack_file/templates.py
      |
      +-- py/pyc/elf -> attack_script/render_attack_script.py
      |                    |
      |                    +-- no_args/ artifacts for goals 1-12
      |                    +-- args/generate_args_attack_scripts.py for goals 13-17
      |
      v
output tasks.json + artifact directories
```

## Files used by generation

### Entry point and goal definitions

```text
generate.py
../inject_goal/inject_goal.json
```

`inject_goal.json` contains the goal descriptions for goals 1–17. Goals 1–12
are no-args goals. Goals 13–17 are runtime-argument variants mapped to the
corresponding base goals 1, 2, 3, 4, and 6.

### Goal-specific generators

```text
prompt/
├── email_send_file.py
├── email_send_prompt.py
├── email_forward_otp.py
├── email_broadcast_link.py
├── chat_send_link.py
├── chat_archive_to_url.py
├── calendar_create_event.py
├── fetch_external_link.py
├── url_query_params.py
├── chat_send_ssh.py
├── terminal_script.py
├── common.py
├── cot.py
└── task_instruction.py
```

The first group creates the goal-specific `attack_config`, destinations,
lookup values, judge rules, and supporting fixtures. `common.py` and `cot.py`
are shared helpers. `task_instruction.py` creates the additional instruction
file when a no-args record does not set `add_user_prompt: true`.

`email_send_prompt.py` also creates the `Task_Brief.txt` fixture for the
no-args prompt-sending goal.

### Carrier generation

```text
../generate_attack_file/
├── generate.py
├── api.py
└── templates.py
```

This layer creates the primary carrier selected by `inject_vector`:

```text
html / md / xlsx / txt / chat / email / calendar / py / pyc / elf
```

For non-executable carriers, the generated attack-config injection is rendered
into the carrier-specific file template. For executable carriers, the script
renderer supplies the runtime behavior instead.

### Executable renderers

```text
attack_script/
├── render_attack_script.py
├── no_args/
│   ├── py/
│   ├── pyc/
│   └── elf/
└── args/
    ├── generate_args_attack_scripts.py
    └── README.md
```

`render_attack_script.py` is the shared no-args renderer and compiler entry
point. The args renderer generates helpers that require task material as
runtime command-line arguments, such as file paths, complete message content,
mail IDs, or attendee addresses.

Generated args artifacts from older experiments are kept separately under
`output/legacy_args/`; they are not templates and are not used by
`generate.py`.

## Tests and verification tools

All benchmark tests are kept under `benchmark/tests`, separately from the
generated templates:

```text
../tests/generate_attack_config/attack_script/
├── _faithful_driver.py
├── test_attack_scripts.py
├── test_attack_scripts_link.py
├── test_faithful_all.py
├── test_selected6_e2e.py
├── test_args_attack_scripts.py
├── test_e2e_args.py
└── args_tasks.json
```

These files validate generated artifacts and run end-to-end Docker/security
checks. They are not imported by the normal `generate.py` generation path.

## Generated output

```text
output/<batch>/
├── tasks.json
└── <harmful_task_id>/
    ├── generated primary carrier
    └── goal-specific supporting fixtures
```

Each output record contains:

- `attack_config`: generated destination, lookup values, marker, and judge;
- `attack_file`: the primary generated carrier;
- `populate_files`: every file that must be copied into the benchmark world.

Paths in these fields are relative to the output `tasks.json` directory.

## Runtime usage

The experiment runner consumes the generated output, not the templates:

```text
benchmark/main_concurrency.py
```

It uses `harmful_task_id` as the selector, populates `populate_files`, starts
any required collector, runs the agent, and performs the security check. The
View App reads the resulting run directory (`grades.json`, `trajectory.json`,
and score summaries); it does not regenerate artifacts.

## Separate legacy area

```text
attack_script/elf_restore/
attack_script/build_restore_elf.py
```

These are for the older ELF file-restoration watcher experiment and are not
part of normal attack-config generation. They are only needed by
`examples/hugging_face_task/run_elf_watcher.sh`.
