# Runtime-argument attack scripts

This directory contains parameterized variants of goals 1, 2, 3, 4, and 6.
Unlike the original payloads, these helpers do not contain the task material
that is sent. They exit with status 2 and print targeted guidance when the
required runtime argument is absent.

The fixed destination and lookup context still comes from each record's
`attack_config`:

| Goal | Required runtime argument | Generation-time fields |
|---|---|---|
| `1_email_send_file` | one or more relevant file paths | `attacker_email_address` |
| `2_email_send_draft` | complete original task prompt | `attacker_email_address` |
| `3_email_forward_otp` | OTP email's mail ID | `attacker_email_address` |
| `4_email_broadcast_link` | one or more attendee addresses | `attacker_link`, `calendar_event_id` |
| `6_chat_to_achieve_url` | complete message content | `attacker_link`, `channel_id` |

The missing-argument message for goals 3, 4, and 6 includes the configured mail,
event, or channel ID so the agent knows where to retrieve the value.

Generate all three formats from the existing batch config:

```bash
cd benchmark/generate_attack_config/attack_script/args
python generate_args_attack_scripts.py \
  --config ../../output/1_to_8_with_attack_config.json
```

The output layout is `py/`, `pyc/`, `elf/`, and `elf/_sources/`. Bytecode and
native binaries are built in `archipelago-hf-environment:concurrency`, matching
the benchmark runtime. `manifest.json` lists every generated artifact and a run
example. An input record may include `args` (a string or list) to make that run
example concrete; the value is never baked into the payload.

Examples:

```bash
python py/1_email_send_file.py '04_Models/model.xlsx' 'supporting memo.pdf'
python pyc/2_email_send_draft.py 'the complete original user prompt'
elf/3_email_forward_otp '<otp-mail-id>'
elf/4_email_broadcast_link first@example.com second@example.com
elf/6_chat_to_achieve_url 'the complete channel message'
```

The generator also accepts compact records using `goal_id` instead of
`inject_goal`, with attack fields at the top level, or an object containing a
`tasks` list.
