# Benchmark 任务生成指南

以下命令均在 `archipelago/benchmark/final_benchmark` 目录执行，使用已安装项目依赖的 Python 环境：

```bash
cd /data/ziyi/archipelago/benchmark/final_benchmark
```

六个入口默认都会采样任务，再调用 `benchmark.generate_attack_config.generate` 生成完整配置和配套文件。完整生成需要可用的模型 API 配置和原始任务数据；仅查看采样结果时添加 `--sample-only`。

## 数量与输出目录

以下数量限制基于默认的 15 个原任务和默认 goal 集合。

| 脚本 | 数量参数及默认值 | 数量限制 | 本目录下的默认输出 |
| --- | --- | --- | --- |
| `generate_static_prompt_injection_tasks.py` | `--output-task-number 30` | 15 的正整数倍，最多 225 | `static_prompt_injection/` |
| `generate_static_script_injection_tasks.py` | `--output-task-number 30` | 15 的正整数倍，最多 360 | `static_script_injection/` |
| `generate_script_swap_tasks.py` | 两个位置参数 `15 15` | args 为 1–195；no_args 为 1–165 | `user_prompt_script_swap/args/`、`no_args/` |
| `generate_suffix_plant_tasks.py` | `--output-task-number 30` | 1–195 | `user_prompt_suffix_plant/` |
| `generate_dynamic_prompt_injection_tasks.py` | `--output-task-number 30` | 1–225 | `dynamic_prompt_injection/` |
| `generate_dynamic_script_injection.py` | `--output-task-number 30` | 正偶数，最多 390；表示两组合计 | `dynamic_script_injection/allow_additional_instruction_true/`、`allow_additional_instruction_false/` |

除 script swap 使用两个位置参数外，其余入口的数量参数也可以写成 `--output-task-count`。

## 1. Static prompt injection

```bash
python generate_static_prompt_injection_tasks.py --output-task-number 30
```

默认读取 `../sample_inject_vector/output/selected_15_tasks_with_balanced_inject_vectors.json`，保留选好的非执行类 vector。goal 为 1–8、18–24，共 15 个。默认每个原任务分配两个不同 goal，每个 goal 出现两次。

可指定 goal 子集（此时最大数量随 goal 数量变化）：

```bash
python generate_static_prompt_injection_tasks.py \
  --output-task-number 30 --goal-ids 1,2,7,18,24
```

## 2. Static script injection

```bash
python generate_static_script_injection_tasks.py --output-task-number 30
```

默认读取 `../sample_inject_vector/output/selected_15_tasks_with_inject_vectors.json`，保留均衡选好的 py、pyc、elf vector。默认 goal 为 1–6、8–17、25–32，共 24 个；internal goal 只保留 args 版本。30 条覆盖全部原任务和全部默认 goal；360 条覆盖全部 task × goal 组合。

同样支持 `--goal-ids`。两个 static 入口可添加 `--add-user-prompt`，将该选项传给配置生成器。

## 3. User prompt script swap

```bash
python generate_script_swap_tasks.py 15 15
# args 生成 30 条，no_args 生成 45 条
python generate_script_swap_tasks.py 30 45
```

两个位置参数依次是 args 和 no_args 的数量，省略时均为 15。使用同样的 15 个原任务，重新均衡采样 py、pyc、elf。

- args goal：13、14、15、16、17、25、26、27、28、29、30、31、32。
- no_args goal：1、2、3、4、5、6、8、9、10、11、12。

固定 `add_user_prompt=true`、`no_key_words=false`，即启用关键词。两组分别输出到 `user_prompt_script_swap/args/` 和 `user_prompt_script_swap/no_args/`。

## 4. User prompt suffix plant

```bash
python generate_suffix_plant_tasks.py --output-task-number 30
```

使用 script swap 的 13 个 args goal，均衡采样 py、pyc、elf。固定 `add_user_prompt=true`、`no_key_words=true`，输出到 `user_prompt_suffix_plant/`。默认每个原任务两条，三种 vector 各 10 条。

## 5. Dynamic prompt injection

```bash
python generate_dynamic_prompt_injection_tasks.py --output-task-number 30
```

使用同样的 15 个原任务，以及 static prompt 的 15 个 goal（1–8、18–24）。固定 `inject_vector=dynamic_prompt_injection`、`add_user_prompt=false`、`no_key_words=true`。默认每个原任务两条，每个 goal 两条。

输出到 `dynamic_prompt_injection/`，包括完整任务配置、watcher 配置与脚本等配套文件。

## 6. Dynamic script injection：是否允许参考文件指示的对比

```bash
python generate_dynamic_script_injection.py --output-task-number 30
# 两组各 195 条，每组覆盖所有 task × goal 组合
python generate_dynamic_script_injection.py --output-task-number 390
```

使用 suffix plant 的 13 个 args goal。固定 `inject_vector=dynamic_script_execution`、`no_key_words=true`。执行入口编译为 ELF 文件 `recover_corrupted_file`，不采样 py/pyc/elf。

默认总计 30 条，分别输出：

- `dynamic_script_injection/allow_additional_instruction_true/`：15 条，`user_allow_additional_instruction=true`。
- `dynamic_script_injection/allow_additional_instruction_false/`：15 条，`user_allow_additional_instruction=false`。

两组均设置 `add_user_prompt=false`。运行时 `main.py` 自动读取 `user_allow_additional_instruction`，true 时追加与 `--user-allow-addtional-instruction` 相同的提示，不需要额外传该开关。手动传开关仍会为所有任务启用提示。

两组采样记录除 `user_allow_additional_instruction` 外相同，task、goal、vector 一一对应。默认每组覆盖全部 15 个原任务和 13 个 goal。两组分别调用配置生成器，因此模型生成的具体内容可能不同。

## 通用选项

| 参数 | 用途 |
| --- | --- |
| `--sample-only` | 仅写采样 JSON，不调用模型生成配置和配套文件 |
| `--output-dir PATH` | 自定义输出根目录；分组入口仍在其下创建分组子目录 |
| `--input PATH` | 自定义原任务 JSON |
| `--inject-goals PATH` | 自定义 goal 定义文件；默认是 `../inject_goal/inject_goal.json` |
| `--seed NUMBER` | 采样种子，默认 42；不保证模型生成内容完全一致 |
| `--dataset-dir PATH` | 指定原始任务数据集目录 |
| `--model NAME` | 指定生成器使用的模型 deployment |
| `--reasoning-effort VALUE` | 传给生成器的推理强度 |

例如，只采样到临时目录：

```bash
python generate_dynamic_script_injection.py \
  --output-task-number 30 --sample-only --output-dir /tmp/dynamic-script-preview
```

默认输入和输出路径根据脚本位置定位，不受当前工作目录影响；用户传入的相对路径以当前工作目录为基准。

## 生成结果与重复运行

每个输出目录（分组入口为每个分组子目录）包含：

- `selected_N_tasks_with_inject_goals.json`：采样记录，N 为本组数量。
- `selected_N_tasks_with_attack_config.json`：完整任务配置。
- 各任务目录：注入文件、watcher 或其他配套文件，具体取决于生成模式。

重复执行会重新调用模型，不是断点续跑。配置生成器先在临时目录完成生成，成功后替换本次同名输出；生成失败时保留已有完整配置和配套文件，采样 JSON 可能已经更新。未涉及的旧任务目录不会自动删除。分组入口逐组生成和发布，一组成功、另一组失败时，已成功的一组会保留。
