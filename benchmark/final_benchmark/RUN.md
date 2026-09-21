# 启动 final benchmark 实验

## 统一全量入口

在仓库根目录执行。同一个接口支持任意已有模型配置，也支持多个模型：

```bash
# DeepSeek：180 个任务，全局并发 64
/data/ziyi/.venv/bin/python benchmark/run_models_parallel.py --models deepseekv4

# Gemini：180 个任务
/data/ziyi/.venv/bin/python benchmark/run_models_parallel.py --models gemini36

# 两个模型共 360 个任务，共用 64 个槽位
/data/ziyi/.venv/bin/python benchmark/run_models_parallel.py --models deepseekv4 gemini36
```

`--models` 的名称对应 `benchmark/orchestrator_config_<名称>.json`。
在终端配置所选模型的认证信息，以及 Gemini judge 的 Vertex 凭据。
默认任务根目录为 `benchmark/final_benchmark`，包含 8 个 batch、每个模型 180 个任务。
模型和类别交错进入统一队列，全局并发默认 64，不按 batch 串行等待。
步数和推理强度使用各模型配置，默认不启用 timer。
可以用 `--concurrency` 调整并发，`--categories` 选择类别，`--input-root` 切换任务集。
`--dry-run` 仅检查配置并打印队列，`--skip-build` 复用已有镜像。

临时空间保护内置在同一个入口，默认使用数据盘上的
`benchmark/output/tmp/full_benchmark/final-batch-*`，也可传 `--temp-root`。
临时目录必须位于独立数据盘，`TMPDIR`、`TMP`、`TEMP` 均指向本次运行的独立目录。
每个任务正常结束时释放其 Python 临时文件。整个任务池结束或收到 Ctrl+C/SIGTERM 后，
等待任务和 Docker 清理完成，再删除本次运行的临时目录。
其他任务的临时目录、缓存和实验结果不会删除。SIGKILL 或主机断电无法执行退出清理。

启动前及运行期间每 2 秒检查临时目录、输出目录和系统盘的空间。
数据盘默认至少保留 30 GiB，系统盘默认至少保留 10 GiB。
空间不足会停止任务池并取消待运行任务。这不是磁盘配额，其他进程仍可能同时消耗空间。

结果默认保存在 `benchmark/output/final_benchmark/parallel_<时间>_<编号>/`，
下面按模型和类别分目录，整体报告是根目录的 `manifest.json`。
每次启动创建新实验，不自动续跑。

只重跑旧 batch 中进程退出码非零的任务：

```bash
/data/ziyi/.venv/bin/python benchmark/run_models_parallel.py \
  --retry-failed parallel_20260915_001732_e2bab06c --concurrency 6
```

也可传入旧 batch 的完整目录。添加 `--dry-run` 可先查看任务清单。
任务从头执行，沿用旧 batch 保存的模型配置和任务 JSON，以及原任务资源目录。
正常结束且 ASR 为零的任务不重跑，尚未启动或没有退出记录的任务也不在此参数范围内。
结果写入新 batch，manifest 的 `retry_of` 记录来源，旧结果保留，不自动合并统计。

添加 `--merge-into-original` 可将每个已结束的重跑任务覆盖回原 batch，
自动刷新原 manifest、类别 score_summary 和已有的 watcher setting_summary.{md,csv,json}。
旧任务文件和退出记录保存在原目录的 `retry_backups/<重跑 batch>/`，重跑日志也复制回原目录。
重跑仍然失败时会更新失败记录，可以再次使用同一条命令重试。

## 跨模型、跨类别统一并行

在 `archipelago` 目录执行：

```bash
/data/ziyi/.venv/bin/python benchmark/run_models_parallel.py \
  --models gemini36 gemini37 gemini38 gpt_astra_low sonnet5 \
  --input-root benchmark/all_category_test \
  --output-root benchmark/output/all_category_test \
  --concurrency 64
```

五个模型各运行 24 个任务，共 120 个任务组合。模型和类别交错排队，共用一个最多 64 槽位的任务池；任务结束后立即补入下一个。并发限制包含环境初始化、agent 执行和评分的完整任务流程。

镜像在启动任务前统一构建一次，每个槽位有独立端口和运行网络。模型配置和任务 JSON 按模型、类别复制到本次输出目录，配套文件仍从输入任务目录读取。不要在运行期间改动输入任务资源。

输出保存在 `benchmark/output/all_category_test/parallel_<时间>_<随机后缀>/`，下面按模型、类别保存独立日志、任务轨迹及 `score_summary.json`。根目录 `manifest.json` 持续更新全部任务的状态和每个模型/类别的指标，不混合不同模型的分数。

添加 `--dry-run` 只检查输入并打印任务队列，不调用模型或 Docker；已有镜像可添加 `--skip-build`。Ctrl+C 或 SIGTERM 停止排队并清理运行中的任务和共享代理。单个任务失败后继续其他任务，最终退出码为非零。

## 按类别顺序运行

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

# 使用抽样任务集（路径相对于当前工作目录）
python run_experiments.py all --model gpt_astra_low --input-root ../all_category_test --output-root ../output/all_category_test
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
