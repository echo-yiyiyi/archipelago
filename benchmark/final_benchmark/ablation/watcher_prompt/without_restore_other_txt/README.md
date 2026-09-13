# Keep other instruction TXT files after the first is read

The same 10 task/goal records, configs, instruction templates and auxiliary files
are copied from ../with. Only the bundled watcher's tick() method is disabled.
Initial file archiving, corrupted-file replacement and instruction TXT creation
remain the baseline behavior.

Reading the first generated instruction TXT still selects it, clears pending
injections and prevents new injections, as in with. However, already generated
sibling instruction TXT files and their corrupted source files remain unchanged.
They are not removed or changed to archive notices after that read.

Goal-category activity still triggers the unchanged global restore(): all
original files are restored and all generated instruction TXT files are removed.
This variant disables first-read sibling cleanup, not goal-triggered recovery.

Task/artifact alignment and functional tests pass, including corruption before
selection, retention of sibling prompts after selection and full restoration at
completion. No model evaluation has been launched.
