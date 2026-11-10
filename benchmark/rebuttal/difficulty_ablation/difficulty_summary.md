# Old-set difficulty ablation

每个难度覆盖同样的 15 种攻击条件，domain 各 5 个；仅使用 old set。

Each difficulty group contains **n = 15 attack instances**, with **n_ER = 9** for ER. Each instance contributes one evaluated result; the fixed original-set baseline run is shared with the domain ablation.

## Gemini 3.7 Flash

| Difficulty | ASR (%, n=15) | ER (%, n=9) | Mean Score (n=15) |
|---|---:|---:|---:|
| easy | 40.00 | 66.67 | **1.0000** |
| medium | 40.00 | 66.67 | 0.7694 |
| hard | **46.67** | **88.89** | 0.5444 |

## DeepSeek Flash

| Difficulty | ASR (%, n=15) | ER (%, n=9) | Mean Score (n=15) |
|---|---:|---:|---:|
| easy | **53.33** | **88.89** | **0.8444** |
| medium | 46.67 | 66.67 | 0.6389 |
| hard | **53.33** | 66.67 | 0.4222 |


## 统计口径

- 每组 ASR/Score 对 15 种攻击条件等权平均，ER 仅对定义曝光的 9 种条件平均。无缺失评分、无补零。
- 每个模型固定选一轮原 subset 结果，easy/medium/hard 分别取其中 9/3/3 个实例，与新增 6/12/12 个实例的单轮结果合并。每个条件只贡献一次结果，不混用三轮均值。
- 固定基线按 score_summary.updated_at 选择当时最近完成的本机运行，不按 ASR/ER/Score 选择；两种 ablation 共用 single_run_baselines.json。
- Gemini 3.7 Flash 基线：`gemini37_subset_d460da681561`。
- DeepSeek Flash 基线：`deepseek_subset_6b01a674aa46`。
- ASR 是成功数/15，ER 是曝光数/9；百分比分别按 1/15 和 1/9 的步长变化。原 subset 三轮均值与标准差保留在独立的重复性汇总中，不用于本表拼接。
- 本表是单轮完整 15 实例汇总，不报告三轮标准差。
- 原始任务数量：easy=9、medium=3、hard=3。每组均为 15 个攻击实例，不能据此声称每组有 15 个独立原始任务。
- 本表是描述性对比，不构成因果或显著性结论。

## 数据来源

新增结果：
- [Gemini 3.7 Flash / easy](../../output/difficulty_ablation/gemini37/easy/gemini37_old_easy_20261109_173801_93552e39/score_summary.json)
- [Gemini 3.7 Flash / medium](../../output/difficulty_ablation/gemini37/medium/gemini37_old_medium_20261109_173801_93552e39/score_summary.json)
- [Gemini 3.7 Flash / hard](../../output/difficulty_ablation/gemini37/hard/gemini37_old_hard_20261109_173801_93552e39/score_summary.json)
- [DeepSeek Flash / easy](../../output/difficulty_ablation/deepseekv4/easy/deepseekv4_old_easy_20261109_172801_591cb9a2/score_summary.json)
- [DeepSeek Flash / medium](../../output/difficulty_ablation/deepseekv4/medium/deepseekv4_old_medium_20261109_172801_591cb9a2/score_summary.json)
- [DeepSeek Flash / hard](../../output/difficulty_ablation/deepseekv4/hard/deepseekv4_old_hard_20261109_172801_591cb9a2/score_summary.json)

复用结果：

- [三轮原 subset 结果与来源](../subset/deepseek_repeat_comparison.md)
- [原 Gemini 历史结果](../subset/model_results.json)
- [实验条件映射](design_manifest.json)

完整精度、单次成功/曝光计数及逐实例来源见 `difficulty_summary.json`；固定基线见 `../single_run_baselines.json`。
