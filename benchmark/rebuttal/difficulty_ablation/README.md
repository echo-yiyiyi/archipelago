# Old-set 难度对照实验

只使用 `../subset/selected_15_tasks_with_attack_config.json` 中的原始 15 个任务，
不使用 more_tasks/new set。将原 subset 的 S01–S15 攻击条件分别放到 easy、medium、hard，
共 45 个攻击实例；每组各 15 个，每个 domain 各 5 个，覆盖相同的 8 个 category。

| 难度 | 完整实例 | 原实例及结果可复用 | 新增实例 | 不同原始任务 |
|---|---:|---:|---:|---:|
| easy | 15 | 9 | 6 | 9 |
| medium | 15 | 3 | 12 | 3 |
| hard | 15 | 3 | 12 | 3 |
| 合计 | 45 | 15 | 30 | 15 |

同一个 Sxx 跨难度保持 domain、category、goal、vector、leakage_type、
add_user_prompt、no_key_words、user_allow_additional_instruction 一致。
先保留所有原有任务配对，再在相同 domain/目标难度内选择使用次数最少的任务，
并用 task_id 打破平局。easy 每个 domain 的三个任务承载次数为 2、2、1，
medium/hard 每个 domain 只有一个原始任务，各承载 5 种攻击条件。
分配完全确定，不根据已知 ASR/ER/Score 挑选。

## 三组文件

`easy/`、`medium/`、`hard/` 各包含：

- `selected_15_tasks_with_attack_config.json`：该难度完整 15 个实例，可直接传入原 runner。
- `new_tasks_with_attack_config.json`：只包含需要补跑的实例，分别为 6/12/12 个。
- `reused_tasks_with_attack_config.json`：原样保留的实例，分别为 9/3/3 个。
- `selected_15_tasks_with_inject_goals.json`：可审查的任务分配和原始 keyword。
- `generated_Sxx.json` 及对应素材目录：单任务 checkpoint，素材使用组内相对路径。

`design_manifest.json` 保存全部 45 个槽位的对应关系、原难度、目标难度和复用标记。
`reusable_results.json` 列出已完成的本机 subset 重跑中可复用的逐任务 grades 路径，
保留不同重复运行，不把它们混成一次结果，也不使用 new-set 的结果。

## 原 pipeline 生成

原有 15 个实例的记录、配置和素材字节原样复制，并校验一致性。
新增 30 个使用目标 old task 已有的 keyword，不重新抽样 keyword；
调用与前一批相同的 `benchmark.generate_attack_config.generate` 模块，
复用原配置、文件、watcher 和 ELF/PYC 生成流程。
生成模型仍是 Azure `gpt-5.6-sol`，使用新的项目 endpoint 和仓库根 `.env` 的 key。
不显式设置 reasoning effort，沿用原生成器默认行为。凭据不会写入产物。

从仓库根运行：

```bash
agents/.venv/bin/python benchmark/rebuttal/difficulty_ablation/generate.py
```

已完成 checkpoint 会复用。`--prepare-only` 不调用模型，`--validate-only` 检查完整产物。
生成器使用文件锁避免并发写入；源 subset 或设计改变时会拒绝混合生成。

## 多模型运行和 judge

默认只跑新增的 30 个实例，按 easy → medium → hard 顺序运行：

```bash
agents/.venv/bin/python benchmark/rebuttal/difficulty_ablation/run.py \
  --model deepseekv4 --skip-build

agents/.venv/bin/python benchmark/rebuttal/difficulty_ablation/run.py \
  --model gemini37 --skip-build
```

可加 `--difficulty medium` 单独跑一组，或加 `--dry-run` 验证并查看命令。
如果需要完整的新一轮 45 个实例而不复用历史结果，加 `--include-reused`。
运行仍调用 `benchmark/run_concurrency.sh`，包含原任务 grader、attack success 和
适用任务的 exposure judge；评分器的配置、凭据要求沿用原实验。
结果存放在 `benchmark/output/difficulty_ablation/<model>/<difficulty>/<run-id>/`。
同一命令重复执行会开始新一轮模型运行，不会自动跳过已有评测。

默认补跑结果的分母是 6/12/12，不能直接拿它们的汇总当作每组 15 个的结果。
正式比较时，需从同一个既有 subset 运行中取出各组的 9/3/3 个复用结果，
与各组补跑结果合并后再计算 ASR、ER、Score。
每个完整难度组 ASR/Score 的分母为 15，ER 只对 9 个定义 exposure 的实例计算。

现有[汇总表](difficulty_summary.md)采用单轮口径：每个模型固定一轮原 subset 结果，
与新增实例的单轮结果合并，每组恰好 15 个独立计数的 0/1 攻击结果。
固定基线在 `../single_run_baselines.json`，按当时最近完成的本机运行选择，不按表现选择；
与 domain ablation 使用相同基线。ASR 为成功数/15，ER 为曝光数/9。
原 subset 的三轮均值及标准差仍保留在独立的重复性汇总中，不混入本表。

```bash
agents/.venv/bin/python benchmark/rebuttal/difficulty_ablation/summarize.py
```

## 解释限制与验证

这是每个难度 15 个攻击实例，不是每个难度 15 个独立原始任务。
尤其 medium/hard 每个 domain 只有一个任务，难度效果仍与具体任务内容有关。
目标任务相关的 keyword、配置值和素材会变化，控制的是攻击条件和生成规则，
并非所有攻击文件字节相同。复用历史结果还应记录跨日期模型与执行环境的差异。

```bash
agents/.venv/bin/python -m unittest discover \
  -s benchmark/rebuttal/difficulty_ablation -p test_design.py -v
agents/.venv/bin/python benchmark/rebuttal/difficulty_ablation/generate.py --validate-only
```
