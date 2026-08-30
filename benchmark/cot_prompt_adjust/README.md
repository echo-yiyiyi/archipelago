# COT prompt adjustment replay

The observed trajectories show three failure patterns: the model labels the
instruction as prompt injection, silently ignores it, or performs only the
original task.  The five generation prompts are based on the successful
`examples/hugging_face_task/input` variants: matter-level review wording,
collaborator handoffs, specific "Before modifying/reviewing" openings, QA
rationales, and explicit continuation.  They keep the action and task-specific
details unchanged while varying only the natural framing.

`replay_cot_variants.py` finds the first tool result containing the injected
`<think>` block, truncates the trajectory at that message, replaces only that
block with five variants, and optionally resumes each variant for exactly ten
additional turns with Gemini.

Prepare variants offline (uses the previous COT body only as a fallback):

```bash
python benchmark/cot_prompt_adjust/replay_cot_variants.py \
  --source-run benchmark/output/concurrent/run_20260830_110744_8efcb105
```

Generate five new COTs per task with structured output first (set the model to
the deployment you want):

```bash
python benchmark/cot_prompt_adjust/replay_cot_variants.py \
  --source-run benchmark/output/concurrent/run_20260830_110744_8efcb105 \
  --generate-cot --generation-model vertex_ai/gemini-3-flash-preview
```

Run the prepared variants:

```bash
python benchmark/cot_prompt_adjust/replay_cot_variants.py \
  --source-run benchmark/output/concurrent/run_20260830_110744_8efcb105 \
  --run --parallel 8
```

Only the files under `benchmark/cot_prompt_adjust/output` are created or
updated. Tasks whose source trajectory contains no readable injected COT are
recorded as `skipped` rather than inventing a replay position.
