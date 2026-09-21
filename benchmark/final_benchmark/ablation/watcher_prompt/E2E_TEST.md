# Offline watcher integration test

```bash
python3 benchmark/final_benchmark/ablation/watcher_prompt/test_watchers_e2e.py
```

Requires Docker access and the locally built image
`archipelago-hf-environment:concurrency`. Override with `--image IMAGE`.
Use `--output NEW_DIRECTORY` to choose the report location.

The test starts a fresh environment container for each of `without_corrupt`,
`without_restore_other_txt`, and `without_txt`. It does not restart existing
benchmark containers. No host credentials or volumes are passed in; external
networking is disabled with `--network none`.

It uses `/data/populate` for fixtures and watcher files, `/apps` for the installed
code-execution MCP server, and the same post-populate startup hook as benchmark
runs. Agent reads and synthetic shared-folder recovery activity go through the
real MCP code-execution tool. It never calls a model or sends mail.

Fixtures cover eight extensions and deliberately use different stems to avoid
sidecar-name collisions. Office fixtures are minimal XML packages intended for
byte/XML reads via the code tool; this is not an Office-renderer compatibility
test or a replay of a full business task. The original shared-recovery task's
watcher configuration and generated watcher implementation are copied unchanged.

Assertions cover first reads returning original bytes, injection after reads,
no injection of unread files, unchanged instruction content in the selected XLSX
carrier (or its sidecar), setting-specific sibling neutralization/restoration/preservation, no new
injections after selection, byte-for-byte restoration on recovery activity, and
no reinjection after completion. Observer polling uses existence checks to avoid
accidentally selecting an instruction through a diagnostic read.

Reports include the tool calls and outputs, environment logs, watcher logs and a
final filesystem archive. Test-owned containers are removed in `finally`.

Run only the changed setting with `--settings without_corrupt`. In this setting,
all sibling TXT remain but contain only `Please continue with the original task.`;
the selected instruction is unchanged. Goal activity removes all owned notes.

## Application reader coverage

```bash
python3 benchmark/final_benchmark/ablation/watcher_prompt/test_watchers_e2e.py --document-readers
```

Each format independently starts a watcher and is read before and after injection.
TXT/MD/HTML use filesystem read_text_file; CSV and XLSX use sheets read_csv/read_tab;
PDF uses read_pdf_pages; DOCX uses read_document_content; PPTX uses read_slides.
Office fixtures here are complete documents, not the minimal XML fixtures used
in the sibling-lifecycle test. Full prompt lines must be returned by the app,
allowing only representation whitespace and app-added row/paragraph labels.

## Dynamic script recovery ablation

```bash
python3 benchmark/final_benchmark/ablation/watcher_prompt/test_watchers_e2e.py --script-recovery
```

Tests watcher_script/with and direct_arg with the unchanged credit-score task
configuration and ELF, supplying only the synthetic value 730. Includes actual
ELF execution, argument errors, invalid recovery target, private backup state,
sibling restoration, and recovery triggered by the explicit protocol rather
than ordinary shared-folder activity. It does not exercise external-mail,
calendar, or other goal payloads. All ten paired bundles additionally have
static template/payload equality and isolated argument-guard tests in
watcher_script/test_direct_arg.py.
