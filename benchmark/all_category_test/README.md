# Small benchmark sample

This bundle selects 24 tasks from `../final_benchmark`: four each from the four unsplit categories and two each from the four leaf subcategories. It covers 22 distinct attack goals. Selection balanced injection vectors and reduced repeated goals using seed 42; see `manifest.json` for exact tasks.

From the repository root:

```bash
python3 benchmark/run_models_parallel.py --models deepseek_v4_flash \
  --input-root benchmark/all_category_test --concurrency 2
```

The dynamic script true/false groups use matching task and goal pairs.
