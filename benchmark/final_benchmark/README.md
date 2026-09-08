# Final benchmark

## 生成 static prompt injection 任务

以下命令从 `archipelago` 的上一级目录执行：

```bash
python3 archipelago/benchmark/generate_static_prompt_injection_tasks.py \
  --output-task-number 30
```

默认读取 `archipelago/benchmark/sample_inject_vector/output/selected_15_tasks_with_balanced_inject_vectors.json`，保留原任务选好的非执行类 vector。默认可选 goal 为 **1–8、18–24，共 15 个**。

输出数量必须是输入任务数的正整数倍，每个原任务分配的 goal 不重复，且不超过可选 goal 数量。传入 `30` 时，15 个原任务各分配 2 个 goal，每个默认 goal 总共出现 2 次。采样保证全局以及每种 vector 内的 goal 次数差不超过 1。默认随机种子为 `42`，可通过 `--seed` 修改。

### 自定义 goal

`--goal-ids` 支持数字 ID 或完整 goal ID，以空格或逗号分隔：

```bash
python3 archipelago/benchmark/generate_static_prompt_injection_tasks.py \
  --output-task-number 30 \
  --goal-ids 1,2,7,18,24 \
  --seed 123
```

### 仅采样

添加 `--sample-only` 只生成采样 JSON，不调用模型或生成配套文件：

```bash
python3 archipelago/benchmark/generate_static_prompt_injection_tasks.py \
  --output-task-number 30 \
  --sample-only
```

### 输出文件

默认输出目录为 `archipelago/benchmark/final_benchmark/static_prompt_injection/`。以 30 条任务为例：

- `selected_30_tasks_with_inject_goals.json`：采样结果，作为现有 `generate_attack_config` 生成器的输入。
- `selected_30_tasks_with_attack_config.json`：完整任务配置。
- 每个 `harmful_task_id` 对应的目录：注入文件及配套文件，最终 JSON 中的路径相对于输出目录。

最终任务顶层和 `attack_config` 内均设置 `leakage_type`：goal **1、2、3、4、5、6、8** 为 `external`，其余为 `internal`。

### 其他参数与运行条件

| 参数 | 用途 |
| --- | --- |
| `--input` | 指定任务输入 JSON |
| `--output-dir` | 指定输出目录 |
| `--inject-goals` / `--goals-input` | 指定 goal 定义 JSON |
| `--dataset-dir` | 指定原始任务数据集目录 |
| `--model` | 指定 Azure OpenAI deployment |
| `--reasoning-effort` | 设置生成器的推理强度 |
| `--add-user-prompt` | 向生成器传递同名选项 |

完整生成通过当前 Python 解释器调用 `benchmark.generate_attack_config.generate`，需要准备该生成器的依赖、Azure OpenAI 配置和原始任务数据集。生成失败时脚本会报错，采样 JSON 会保留。生成完成后会检查任务 ID、配置和配套文件是否完整。

## 生成 static script injection 任务

使用相同的 15 个原任务，以及已经均衡采样的 `py`、`pyc`、`elf` vector（各 5 条）：

```bash
python3 archipelago/benchmark/generate_static_script_injection_tasks.py \
  --output-task-number 30
```

默认输入为 `archipelago/benchmark/sample_inject_vector/output/selected_15_tasks_with_inject_vectors.json`。默认输出目录为 `archipelago/benchmark/final_benchmark/static_script_injection/`，包含采样 JSON、完整配置 JSON 和每条任务的配套文件。默认会调用配置生成器；只检查采样时添加 `--sample-only`。

默认从 goal 目录中选取所有适用于 script 的目标，目前共 **24 个**：

- external：1–6、8–17，共 16 个，保留普通版和 args 版。
- internal：25–32，共 8 个，只使用 args 版，排除 prompt injection 使用的 7、18–24。

internal 版本对应关系为：7 → 31（agent 根据原任务拟定事件 summary 后传参）；18 → 32（agent 选择任务相关文件后传入一个或多个路径）；19–24 → 25–30（agent 获取对应信息后传参）。标题和源文件路径不在配置生成时预先指定。

30 条输出意味着每个原任务分配 2 个不同 goal，24 个 goal 各出现 1–2 次；360 条输出则覆盖 15 × 24 的全部组合。全局和每种 vector 内的 goal 次数差不超过 1。

参数与 static prompt 入口一致，例如：

```bash
python3 archipelago/benchmark/generate_static_script_injection_tasks.py \
  --output-task-number 30 \
  --goal-ids 25,26,27,28,29,30,31,32 \
  --model aoai-swedencentral-aii-02-gpt-5.6-sol
```

未添加 `--add-user-prompt` 时，每个可执行文件会搭配 `*_Additional_Task_Instructions.txt`，包含运行命令及必要的参数说明。
