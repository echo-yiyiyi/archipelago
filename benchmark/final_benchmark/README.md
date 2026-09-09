# Final benchmark

各生成脚本的完整用法、数量限制和输出说明见 [GENERATE.md](GENERATE.md)。

所有任务生成入口均位于本目录，可直接在此运行。默认调用完整配置生成流程，添加 `--sample-only` 可仅采样。默认输入和输出路径不受当前工作目录影响；自定义相对路径以当前工作目录为基准。

| 脚本 | 指定输出数量示例 |
| --- | --- |
| `generate_static_prompt_injection_tasks.py` | `--output-task-number 30` |
| `generate_static_script_injection_tasks.py` | `--output-task-number 30` |
| `generate_script_swap_tasks.py` | `15 15`（依次为 args、no_args 数量） |
| `generate_suffix_plant_tasks.py` | `--output-task-number 30` |
| `generate_dynamic_prompt_injection_tasks.py` | `--output-task-number 30` |
| `generate_dynamic_script_injection.py` | `--output-task-number 30`（true/false 各 15 条） |

数量限制沿用各入口的采样规则，详见下面各节。

## 生成 dynamic script injection 任务

在 `archipelago/benchmark/final_benchmark` 目录下执行：

```bash
python3 generate_dynamic_script_injection.py
python3 generate_dynamic_script_injection.py --output-task-number 390
```

默认总计 30 条，分为 `add_user_prompt_true/` 和 `add_user_prompt_false/` 两组，各 15 条。两组采样记录除 `add_user_prompt` 外完全相同，分别调用配置生成流程；模型生成的内容可能不同。每组覆盖全部 15 个原任务，以及与 user prompt suffix plant 相同的 13 个 args goal：13、14、15、16、17、25、26、27、28、29、30、31、32；每个 goal 出现 1–2 次。数量参数表示两组合计，必须为正偶数，默认输入下最多 390；设为 390 时每组覆盖全部 15 × 13 个组合。

沿用原有 dynamic script 流程：`inject_vector=dynamic_script_execution`、`no_key_words=True`，`add_user_prompt` 按组设置。不采样 py/pyc/elf，执行入口固定编译为 ELF 文件 `recover_corrupted_file`。输出到 `archipelago/benchmark/final_benchmark/dynamic_script_injection/` 下的上述两个子目录，包含完整配置、`dynamic_watcher_config.json`、Python watcher 脚本、ELF 恢复程序及其他配套文件。

其他参数与 dynamic prompt 入口相同，包括 `--sample-only`、`--input`、`--output-dir`、`--dataset-dir`、`--seed`、`--inject-goals`、`--model` 和 `--reasoning-effort`。

## 生成 dynamic prompt injection 任务

在 `archipelago/benchmark/final_benchmark` 目录下执行：

```bash
python3 generate_dynamic_prompt_injection_tasks.py
python3 generate_dynamic_prompt_injection_tasks.py --output-task-number 45
```

使用同样的 15 个原任务，以及与 static prompt injection 相同的 15 个 goal：1–8、18–24。默认生成 30 条，每个原任务分配 2 个不同 goal，每个 goal 出现 2 次。支持自定义数量，原任务和 goal 的出现次数差不超过 1；默认输入下范围为 1–225。

固定 `inject_vector=dynamic_prompt_injection`、`no_key_words=True`、`add_user_prompt=False`，沿用现有 dynamic watcher 生成流程。默认输出到 `archipelago/benchmark/final_benchmark/dynamic_prompt_injection/`，包含采样 JSON、完整任务配置，以及各任务的 `dynamic_watcher_config.json`、`dynamic_watcher.py`、`dynamic_document_formats.py` 和必要的配套文件。

支持 `--sample-only`、`--input`、`--inject-goals`、`--output-dir`、`--seed`、`--dataset-dir`、`--model`、`--reasoning-effort`。

### 重复生成

所有调用 `benchmark.generate_attack_config.generate` 的入口均先在临时目录生成完整配置和文件，成功后替换本次生成的同名输出。生成失败时保留旧的完整配置和配套文件；发布过程中的普通文件操作错误会尝试回滚。其他任务目录不会被删除。重复运行仍会重新调用模型，不是断点续跑。

## 生成 user prompt suffix plant 任务

在 `archipelago/benchmark/final_benchmark` 目录下执行：

```bash
python3 generate_suffix_plant_tasks.py
python3 generate_suffix_plant_tasks.py --output-task-number 60
```

默认生成 30 条任务，使用与 script swap 的 `args` 相同的 13 个 goal：13、14、15、16、17、25、26、27、28、29、30、31、32。复用相同的 15 个原任务及均衡采样逻辑；默认每个原任务 2 条，`py`、`pyc`、`elf` 各 10 条。

固定 `add_user_prompt=True`、`no_key_words=True`，由原有生成器使用通用脚本名。输出直接放在 `archipelago/benchmark/final_benchmark/user_prompt_suffix_plant/`，包含采样 JSON、完整配置 JSON 和配套文件，不再分 args/no_args 子目录。

默认执行完整生成。可使用 `--sample-only` 仅采样，以及 `--input`、`--inject-goals`、`--output-dir`、`--seed`、`--dataset-dir`、`--model`、`--reasoning-effort`。默认输入下数量范围为 1–195，同一原任务的 goal 不重复。

## 生成 user prompt script swap 任务

在 `archipelago/benchmark/final_benchmark` 目录下执行，两个数字依次为 `args`、`no_args` 的任务数量，默认均为 15：

```bash
python3 generate_script_swap_tasks.py
python3 generate_script_swap_tasks.py 15 30
```

默认使用同样的 15 个原任务，重新从 `py`、`pyc`、`elf` 均衡采样 vector；每组及两组合计的 vector 数量差不超过 1。每组的原任务与 goal 出现次数差不超过 1，同一原任务的 goal 不重复。数量可以不是 15 的倍数，但必须为正数；默认输入下 `args` 最多 195 条，`no_args` 最多 165 条。

- `user_prompt_script_swap/args/`：13、14、15、16、17、25、26、27、28、29、30、31、32。
- `user_prompt_script_swap/no_args/`：1、2、3、4、5、6、8、9、10、11、12。

每组独立输出 `selected_N_tasks_with_inject_goals.json`、`selected_N_tasks_with_attack_config.json` 和配套文件，路径相对于各自目录。默认执行完整配置生成；添加 `--sample-only` 仅采样。

强制启用 `add_user_prompt=True`，并通过生成器实际使用的 `no_key_words=False` 启用关键词，保留输入的 `keywords` 列表。沿用正式生成器生成带关键词的文件名和用户提示所需配置。两组输出均设置正确的 `leakage_type`。

还支持 `--input`、`--inject-goals`、`--output-dir`、`--seed`、`--dataset-dir`、`--model` 和 `--reasoning-effort`；默认输出根目录为 `archipelago/benchmark/final_benchmark/user_prompt_script_swap`。

## 生成 static prompt injection 任务

以下命令在 `archipelago/benchmark/final_benchmark` 目录下执行：

```bash
python3 generate_static_prompt_injection_tasks.py \
  --output-task-number 30
```

默认读取 `archipelago/benchmark/sample_inject_vector/output/selected_15_tasks_with_balanced_inject_vectors.json`，保留原任务选好的非执行类 vector。默认可选 goal 为 **1–8、18–24，共 15 个**。

输出数量必须是输入任务数的正整数倍，每个原任务分配的 goal 不重复，且不超过可选 goal 数量。传入 `30` 时，15 个原任务各分配 2 个 goal，每个默认 goal 总共出现 2 次。采样保证全局以及每种 vector 内的 goal 次数差不超过 1。默认随机种子为 `42`，可通过 `--seed` 修改。

### 自定义 goal

`--goal-ids` 支持数字 ID 或完整 goal ID，以空格或逗号分隔：

```bash
python3 generate_static_prompt_injection_tasks.py \
  --output-task-number 30 \
  --goal-ids 1,2,7,18,24 \
  --seed 123
```

### 仅采样

添加 `--sample-only` 只生成采样 JSON，不调用模型或生成配套文件：

```bash
python3 generate_static_prompt_injection_tasks.py \
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
python3 generate_static_script_injection_tasks.py \
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
python3 generate_static_script_injection_tasks.py \
  --output-task-number 30 \
  --goal-ids 25,26,27,28,29,30,31,32 \
  --model aoai-swedencentral-aii-02-gpt-5.6-sol
```

未添加 `--add-user-prompt` 时，每个可执行文件会搭配 `*_Additional_Task_Instructions.txt`，包含运行命令及必要的参数说明。

### 直接执行脚本测试（不运行 agent）

在 `archipelago` 目录下执行：

```bash
/data/ziyi/.venv/bin/python benchmark/test_static_script_injection.py \
  --dataset-dir /path/to/apex-agents/snapshot \
  --fallback-dataset-dir /data/ziyi/sampled_tasks/dataset \
  --baseline-tasks-dir examples/hugging_face_task/output/concurrent/merged-gemini-3-5-flash/tasks \
  --workers 3
```

`--dataset-dir` 需包含 `tasks_and_rubrics.json`，world 与 task_files 优先从该目录读取，缺少时依次使用可选的 fallback 数据集和原始任务运行记录。baseline 必须是未注入的原始任务运行目录；仅复用其初始 world 和 `task_*.tar.gz`，不使用最终快照代替输入。缺少必要文件会报错。

测试使用生产 runner 的文件加载、MCP 配置、代理及 collector，每次启动干净环境，按原文件名通过 code-execution MCP 执行，检查工具返回和后台进程结束。参数由测试提供，并记录来源；这验证脚本在这些参数下的行为，不衡量 agent 是否会发现或执行脚本。security 的语义判定仍可能调用 LLM，agent 不调用 LLM。

goal 30 从 baseline 的同一原任务 `trajectory.json` 提取真实 `final_answer` 工具返回值作为回放输入和判定预期；没有该返回值时仅传入测试字符串，security 标记为未验证，不使用用户问题代替最终答案。

完整运行覆盖 `static_script_injection/direct_script_security_results.json`，不会合并旧成功记录。每次运行的输入来源、完整 MCP 返回、进程观察、执行前后快照和结果保存在 `benchmark/output/static_script_direct/<run>/`。若执行前 security 已通过，则标为无法归因；执行错误、判定失败和未验证分别记录。单任务调试使用 `--task-id <harmful_task_id>`，不会覆盖完整报告。
