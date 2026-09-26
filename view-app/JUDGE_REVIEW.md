# Human judge review

Open `/judges` and enter an annotator ID. New IDs are created automatically;
existing IDs reopen their annotations. IDs are case insensitive, and surrounding
spaces are removed. This is intended for a trusted team: anyone entering the same
ID can access that annotator's work. Do not expose the service directly to the
public internet.

## Prepare a review round

From the repository root:

```sh
python view-app/scripts/prepare_judge_round.py --round review-v1
```

The default `goal-balanced` policy selects 40 exposure cases: 20 LLM positives
and 20 LLM negatives, covering every raw goal ID with an eligible saved judge
record and taking one or two cases per goal. Argument variants remain separate
goals. It selects 20 safety cases: four from each of the five semantic goal
families, including every eligible negative decision from an actual LLM call.
Predicted positive and negative strata are based on LLM outputs, not human labels.

Within those constraints, sampling maximizes reuse of matching legacy annotations.
Remaining ties use a fixed random seed. Each task run can appear only once per
judge type. An impossible quota raises an error without creating a partial round.
The round report records counts, availability, and missing strata. The local
`excluded_cases.json` list excludes results superseded by corrected reruns.

The sampler accepts only saved judge inputs with a valid binary result and no
error. It does not call an LLM. Each round freezes the selected inputs and
outputs; later changes to source runs do not alter that round. A round ID cannot
be overwritten. The latest round is shown by default. Use `--policy legacy`
only to reproduce the earlier sampling method.

## Local data and annotator privacy

The first launch backs up the annotation database to
`annotations.before-multiuser.sqlite3`. Previously anonymous annotations and
their history are assigned to the reviewer specified by
`data/judge_review/reviewer-config.json`:

```json
{"legacy_reviewer": "legacy"}
```

Without that file, the default ID is `legacy`. Put a personal ID only in the
local configuration file. The entire `data/judge_review/` directory is ignored
by Git, including the database, exports, saved rounds, and local configuration.
Existing reviewer IDs in an already migrated database are left intact.

The legacy `annotations` table remains available to earlier audit scripts.
New reviews live in `review_labels`, keyed by round, case, and reviewer;
revisions are preserved in `review_events`. Old annotations outside the selected
round remain in the database.

Before submitting a case, the interface hides its LLM output and other
annotators' judgments from lists, search, exports, and details. Submitting
reveals only that case. The server determines the reviewer from the current
session; drafts are separate for each reviewer and round. The first submitted
judgment is preserved, and revisions after viewing results are recorded as
nonblind. Imported legacy annotations are marked `legacy=true, blind=false`.
The export includes both `first_annotation` and the latest `annotation`.

## Run the app

```sh
python view-app/app.py
```

By default, the app listens on `127.0.0.1:8765`. Remote annotators can use
port forwarding. Restart an existing server after changing the code.
