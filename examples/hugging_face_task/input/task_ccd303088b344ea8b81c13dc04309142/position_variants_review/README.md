# Position variants review

Prepared only; no run has been started. Each case contains a trajectory, a `varient_position.json`, and (for new-file cases) a `world_overlay` file.

Existing-position trajectories are truncated immediately after the injected tool result. New-file trajectories contain only the original system and first user messages. All cases request the same email action and are configured for five repeats. New-file cases use 10 additional turns; trajectory-position cases use 5.

For cases 01 and 02, pass their `world_overlay` directory through the new `--world-overlay` option; its contents are loaded into `/filesystem` after the original world and task files. Every run must set `HF_EXPERIMENT_NAME=email_send_file`; position names are grouping labels and are not valid security-judge variant names.
