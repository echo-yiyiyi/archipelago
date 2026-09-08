# Dynamic 8+11+11 token usage

See `DYNAMIC_TASK_COST.md` for the corresponding official-price cost estimate.

Audit clarification: these counters sum every recorded main-agent model
response. They exclude additional summarization calls (whose usage is not
tracked), grading/security judge calls, and attempts without returned usage.
They describe recorded per-attempt consumption, not full account billing.

Data source: `benchmark/output/concurrent/consolidated_dynamic_20260906_155310`.
Each complete model row contains exactly 30 canonical tasks: 8 dynamic-prompt,
11 dynamic-script allow, and 11 dynamic-script no-allow tasks. Duplicate retries
are not counted.

`Input` is `trajectory.json → usage.prompt_tokens`; `Output` is
`usage.completion_tokens`; and `Total = Input + Output`. These values sum usage
over every model call in a task, so repeated context is counted. Cached input is
already included in Input and must not be added again. Reasoning tokens are also
reported separately but are not added to Total again.
All averages are rounded independently to the nearest token, so displayed
Input + Output can differ from displayed Total by one token.

Explicit max-step exhaustion remains part of the 30-task experiment and retains
the tokens it consumed. It accounts for one DeepSeek task and three Gemini
tasks. Provider, watcher, initialization, and interrupted failures are excluded.

## Average per task across all 30 tasks

| Model | Tasks | Avg input | Avg output | Avg total | Avg cached input | Avg reasoning | Avg model calls |
|---|---:|---:|---:|---:|---:|---:|---:|
| Sol | 30 | 463,769 | 6,664 | 470,433 | 376,592 | 3,102 | 21.00 |
| GLM 5.3 | 30 | 748,089 | 39,327 | 787,416 | 607,104 | 33,375 | 25.97 |
| DeepSeek V4 | 30 | 1,836,833 | 51,668 | 1,888,501 | 1,690,176 | 38,283 | 44.93 |
| Gemini | 30 | 3,106,569 | 55,826 | 3,162,395 | 2,572,242 | 38,677 | 69.90 |
| Kimi K3 | 30 | 427,575 | 15,219 | 442,794 | 366,959 | 9,625 | 19.67 |

## Average per task by setting

| Model | Setting | Tasks | Avg input | Avg output | Avg total |
|---|---|---:|---:|---:|---:|
| Sol | Dynamic prompt | 8 | 411,437 | 5,986 | 417,422 |
| Sol | Script allow | 11 | 488,259 | 7,112 | 495,370 |
| Sol | Script no-allow | 11 | 477,340 | 6,709 | 484,049 |
| GLM 5.3 | Dynamic prompt | 8 | 517,170 | 32,805 | 549,975 |
| GLM 5.3 | Script allow | 11 | 1,031,949 | 48,618 | 1,080,567 |
| GLM 5.3 | Script no-allow | 11 | 632,170 | 34,780 | 666,950 |
| DeepSeek V4 | Dynamic prompt | 8 | 1,380,491 | 45,617 | 1,426,108 |
| DeepSeek V4 | Script allow | 11 | 2,218,541 | 57,527 | 2,276,068 |
| DeepSeek V4 | Script no-allow | 11 | 1,787,009 | 50,210 | 1,837,219 |
| Gemini | Dynamic prompt | 8 | 2,752,345 | 81,124 | 2,833,469 |
| Gemini | Script allow | 11 | 3,311,888 | 46,410 | 3,358,298 |
| Gemini | Script no-allow | 11 | 3,158,867 | 46,842 | 3,205,710 |
| Kimi K3 | Dynamic prompt | 8 | 349,886 | 14,395 | 364,281 |
| Kimi K3 | Script allow | 11 | 544,388 | 17,630 | 562,018 |
| Kimi K3 | Script no-allow | 11 | 367,263 | 13,407 | 380,671 |

## Opus coverage limitation

Opus does not have a comparable 30-task sample because the provider rejected
most calls for insufficient credit. Its only completed dynamic-script-allow
task used 360,814 input tokens, 7,589 output tokens, and 368,403 total tokens
across 14 calls. This is a `1/30` sample and is not an average for the suite.

## Opus historical 10-task sample

As a separate estimate, 10 tasks were sampled from the 29 complete Opus tasks
run on September 4–5, 2026. A complete candidate requires
`trajectory.status == "completed"` and numeric input, output, and total usage.
For reproducibility, candidate trajectory paths were sorted by the SHA-256 hash
of the path and the first 10 were selected.

| Metric | Opus 10-task sample |
|---|---:|
| Average input | 502,708 |
| Average output | 15,064 |
| Average total | 517,772 |
| Average cached input | 345,195 |
| Average model calls | 21.80 |
| Median total | 473,574 |
| Minimum total | 224,271 |
| Maximum total | 1,041,086 |

| Batch | Task | Input | Output | Total |
|---|---|---:|---:|---:|
| `tasks_20260905_151500_2293966_opus5` | `dynamic_26_save_employee_number_arg` | 619,201 | 23,226 | 642,427 |
| `shared7_opus5_20260905_004434` | `txt_20_save_employee_number` | 437,098 | 14,952 | 452,050 |
| `shared7_opus5_20260905_004434` | `md_19_save_country` | 292,453 | 15,899 | 308,352 |
| `selected6_generic_opus5_20260904_174612` | `py_1_email_send_file` | 483,356 | 11,741 | 495,097 |
| `selected6_opus5_20260904_155407` | `elf_12_terminal_cron_setup` | 559,684 | 18,752 | 578,436 |
| `tasks_20260905_151500_2293966_opus5` | `elf_28_save_client_code_arg` | 1,019,022 | 22,064 | 1,041,086 |
| `tasks_20260905_151500_2293966_opus5` | `pyc_18_copy_file` | 209,078 | 15,193 | 224,271 |
| `selected6_generic_opus5_20260904_174612` | `elf_12_terminal_cron_setup` | 816,907 | 13,745 | 830,652 |
| `tasks_20260905_224035_4033329_opus5` | `dynamic_30_save_final_answer_arg` | 360,814 | 7,589 | 368,403 |
| `selected6_generic_opus5_20260904_174612` | `elf_11_terminal_remote_script` | 229,471 | 7,477 | 236,948 |

This historical Opus sample spans heterogeneous benchmark suites, so it is a
rough model-level token estimate rather than a directly matched comparison with
the canonical 8+11+11 results above. Opus reported zero reasoning tokens for
these trajectories; reasoning usage may be absent from this provider's usage
breakdown rather than literally zero.
