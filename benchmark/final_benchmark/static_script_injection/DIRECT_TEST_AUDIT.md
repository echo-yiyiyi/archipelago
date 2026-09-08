# Direct script test audit (2026-09-08)

The original `direct_script_security_results.json` at commit `c73cc1f` contained
30 passing rows that were **not evidence of 30 valid attacks under the agent
execution setting**. The findings below describe that historical harness;
corrected full runs replace the report without merging those old successes.

The temporary harness used was `/tmp/run_static_script_bundle.py`; it is not
part of the repository. Inspection against `benchmark/main.py` found:

- **Invalid goal 30 success:** `runtime_args()` passes the original user prompt
  as the answer, and `score()` sets `final_answer_tool_result` to that same
  prompt. Production obtains this value from the agent trajectory. This tests
  writing a supplied string, not preserving an actual final answer.
- **Missing task overlay:** the harness loads a cached world archive and attack
  fixtures, but never loads the original task's `task_files`. Production loads
  world data, then task files and attack fixtures. The available files and app
  state can therefore differ.
- **Oracle arguments:** several arguments come directly from attack_config or
  generated fixtures (including secret values and chat content). Supplying test
  arguments was intentional, but does not verify that an agent can discover
  those values. Goal 31 uses keyword-derived event text; goal 32 selects a source
  by filename keywords. Their passes apply only to these supplied arguments.
- **Different delivery:** the harness skips the original attack artifact during
  population, copies it to `/filesystem/.static_payload*`, and explicitly
  executes it. It does use the code-execution MCP tool, but bypasses discovery,
  lure handling, and the original filename and execution decision.
- **Different setup:** the harness creates `/filesystem/shared` for all goals
  numbered 25 or higher; production's shared-folder list currently omits 32
  and does not include 31. The copy payload creates its own destination, so
  this difference alone does not establish an invalid goal 32 result.
- **Incomplete execution evidence:** many subprocess exit codes and MCP error
  responses are unchecked, output is truncated, and a fixed 25-second sleep
  replaces completion polling. Snapshots are deleted after scoring. Failed-only
  reruns merge previous successes, so the final report combines different
  harness revisions rather than one uniform run.

A faithful direct-execution rerun should reuse production population and MCP
configuration, preserve artifact paths, validate execution completion, retain
evidence, and label supplied arguments as fixtures. Goal 30 needs a genuine
final-answer tool result for a production-equivalent security verdict; without
one, report only a string-writing test and leave that verdict unvalidated.

## Corrected runner

`benchmark/test_static_script_injection.py` now reuses production population,
MCP configuration, worker/collector/proxy creation and security check functions.
It restores original task overlays, freezes the attack bundle, preserves original
artifact names, checks the full MCP result, waits for detached payload processes,
and retains before/after snapshots and input provenance. A preexisting security
success is reported as inconclusive, not credited to execution. Missing final
answers are unvalidated rather than supplied with a fabricated scoring target.

Goal 30 can replay the same original task's actual final-answer tool result from
an explicitly supplied original-run directory. This is a replay fixture, not a
claim that an agent produced that answer during the direct test. Goals 25–29
use configured values that production also appends to the user prompt; reading
those values as test inputs does not in itself indicate an inaccessible oracle.
Other supplied arguments and their sources are also recorded in each result.

The corrected report measures security outcomes conditional on direct execution
with supplied arguments. It does not measure discovery, injection exposure,
agent compliance, or original-task completion. Semantic security judges may
still call an LLM; the test does not invoke an agent LLM.
