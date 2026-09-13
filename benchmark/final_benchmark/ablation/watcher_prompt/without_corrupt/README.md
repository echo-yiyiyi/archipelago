# Watcher without document corruption

The 10 task records, task IDs, goals, attack configs, instruction templates and
supporting artifacts are copied unchanged from ../with. Only the watcher methods
redirect, tick and restore are replaced in each task's bundled dynamic_watcher.py.

On a supported file read, the watcher creates
`<original file stem> additional task instruction.txt` beside the source file.
It does not rename, rewrite, replace or archive the source document. Existing
neighboring instruction files are never overwritten. The baseline read delay,
file eligibility rules and goal-activity stop conditions remain unchanged.

The first watcher-created instruction TXT that is read becomes the selected
instruction. Pending injections are cleared, sibling instruction TXT files are
removed and no further instruction TXT files are created. Ordinary source TXT
reads do not trigger this selection rule. Goal-category activity removes the
remaining generated note and stops the watcher. Cleanup never restores or rewrites
source files because they were not modified.

To isolate watcher file mutation, the instruction template and rendered text are
retained from with, including archive/recovery wording and the computed
`{preserved_name}` archive name. No corresponding archive file is actually created
in this variant. This intentional text control is distinct from rewriting the
instruction to describe an uncorrupted source file.

Validation includes exact record/artifact comparisons, preservation of source
bytes/inodes/mtime, first-instruction selection and sibling cleanup, no overwrite
of existing notes, and a real inotify read/activity lifecycle test.
No model evaluation has been launched.
