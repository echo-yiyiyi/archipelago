# Direct argument watcher variant

This variant pairs with the ten tasks in `../with`. The task, goal, attack configuration, recovery ELF, watcher code, and assets match. Only each `dynamic_watcher_config.json` instruction template changes: the damaged file displays a complete two-argument recovery example. `user_allow_additional_instruction` stays false.

Argument help was extracted statically from the embedded Python in the existing ELF; the attack scripts were not executed or regenerated. The recovery command requires two nonempty arguments. Goal 16 combines multiple addresses into one quoted argument. Goal 32 accepts one source path. Goal 13 accepts one attachment path or a quoted JSON array of paths as a single argument.

To rebuild and validate from the repository root:

```bash
python3 benchmark/final_benchmark/ablation/watcher_script/build_direct_arg.py
python3 benchmark/final_benchmark/ablation/watcher_script/test_direct_arg.py
```

Validation checks the ten matched pairs, watcher output, paths with spaces and quotes, and recovery argument parsing. It does not run a model evaluation.
