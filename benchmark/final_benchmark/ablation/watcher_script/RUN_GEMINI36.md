# Gemini 3.6 Flash

两组使用同样的 10 个 task/goal：`with` 和 `direct_arg`。使用仓库的 `orchestrator_config_gemini36.json`，模型为 `vertex_ai/gemini-3.6-flash`，每任务最多 100 steps，timer 关闭。

在仓库根目录运行：

```bash
# 同一 task/goal，两组各跑一次，共 2 次，并发 2。
bash benchmark/final_benchmark/ablation/watcher_script/run_gemini36_smoke.sh

# 两组各 10 个任务，共 20 次，默认共享并发 12。
bash benchmark/final_benchmark/ablation/watcher_script/run_gemini36_all.sh

# 可选：20 次全部并发。
bash benchmark/final_benchmark/ablation/watcher_script/run_gemini36_all.sh --concurrency 20
```

Smoke 默认选择 `13_email_send_file_arg`，task 为 `task_4e38ae1e886d46979130923154324782`。可用 `--goal 16` 选择其他保留的 goal。添加 `--dry-run` 只检查配对并打印运行计划。

结果位于 `benchmark/output/ablation/watcher_script/{smoke|all}_*/parallel_*/`。结束时打印两组 exposure rate 和 ASR，并写入 `setting_summary.md`、`setting_summary.csv`、`setting_summary.json`。分别使用 `prompt_exposure`、`attack_success` 的有效 0/1 评分作分母；缺失评分不算失败，单独报告。Exposure 指 benchmark 的暴露评分，不等于执行恢复脚本的比例。

重新汇总已有运行：

```bash
bash benchmark/final_benchmark/ablation/watcher_script/run_gemini36_all.sh --summarize /path/to/parallel_run
```

样本删减明细见 `subset_manifest.json`；与 watcher_prompt 删除同样的 5 个 task ID，每组内部保持 task/goal 严格配对，两类的 goal 沿用各自原始设置。
