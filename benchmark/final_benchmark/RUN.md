# 启动 final benchmark 实验

在 `archipelago/benchmark/final_benchmark` 目录下，使用安装了项目依赖的 Python 环境执行：

```bash
# 所有类别
python run_experiments.py all --model gemini35 --concurrency 3

# 单个类别；有子类别时会分别运行
python run_experiments.py user_prompt_script_swap --model luna

# 仅一个子类别
python run_experiments.py dynamic_script_injection/allow_additional_instruction_true --model gemini35

# 只检查配置、配套文件并打印命令，不启动实验
python run_experiments.py all --model gemini35 --dry-run
```

`--model gemini35` 自动读取 `benchmark/orchestrator_config_gemini35.json`，`luna` 对应 `orchestrator_config_luna.json`，其他已有配置同理。使用配置中的模型和认证方式；模型简称不会修改配置内容。Docker、模型认证及原始数据集仍需在运行环境中可用。

## Batch 划分

`all` 包含以下 8 个 batch，按顺序运行，每个 batch 内默认并发 3 个任务：

- `static_prompt_injection`
- `static_script_injection`
- `user_prompt_script_swap/args`
- `user_prompt_script_swap/no_args`
- `user_prompt_suffix_plant`
- `dynamic_prompt_injection`
- `dynamic_script_injection/allow_additional_instruction_true`
- `dynamic_script_injection/allow_additional_instruction_false`

每个 batch 目录必须恰有一个 `selected_*_tasks_with_attack_config.json`。缺少完整配置、配套文件或存在多个数量版本时，会在启动任何 batch 前报错，不会自动跳过或猜测版本。动态对比组还会校验新的 allow 字段。

任务级 `add_user_prompt` 和 `user_allow_additional_instruction` 从 JSON 自动读取，无需额外传开关。可选 `--timer` 为所有任务启用五分钟提示和计时工具，默认不启用。

## 输出

默认按输入类别目录组织到 `benchmark/output/final_benchmark/`，例如：

```text
benchmark/output/final_benchmark/
  user_prompt_script_swap/
    args/
      gemini35_user_prompt_script_swap_args_20260909_143434_70c329/
        score_summary.json
        manifest.json
        attack_config.json
        tasks/
        logs/
  summaries/
    gemini35_all_20260909_143434_70c329.json
```

Batch ID 为模型简称＋类别（含子类别）＋本地日期时间＋随机后缀，避免重复运行重名。`--output-root PATH` 可替换输出根目录。

每个 batch 保留 runner 的完整输出和独立分数；`summaries/` 中的实验汇总逐 batch 更新，不将不同类别混合计算分数。任务明细仍在各 batch 的 `score_summary.json` 和 `tasks/` 中。

## 分数含义

| 实验汇总字段 | Runner 原字段 | 分母 |
| --- | --- | --- |
| `asr` | `average_attack_success` | `attack_evaluated_count`：有 attack_success 结果的任务 |
| `average_score` | `average_mean_score` | `completed_task_count`：有可用任务评分的任务 |
| `exposure_rate` | `average_prompt_exposure` | `prompt_exposure_task_count`：有 exposure 结果的任务 |

ASR 和 exposure rate 为 0–1 比例，0.5 即 50%。汇总同时保留每项分母和请求任务数量，缺少该指标时显示 `null`，不将缺失结果当作 0%。当前 runner 对 `add_user_prompt=true` 的任务不输出 exposure，因此 script swap、suffix plant 通常没有这一指标。新版 dynamic 两组均为 `add_user_prompt=false`，allow 字段不触发这个省略规则。

汇总值来自现有评分流程；务必结合 batch 返回码、任务错误和分母判断结果是否完整。没有运行到评分的任务不保证出现在指标分母里。

默认首个 batch 构建镜像，成功后后续 batch 使用 `--skip-build`。已有镜像时可显式传 `--skip-build`。某个 batch 返回失败后继续后面的 batch，最终整体返回非零；Ctrl+C 则停止后续 batch，已完成输出保留。重新运行会创建新 batch，不是断点续跑。
