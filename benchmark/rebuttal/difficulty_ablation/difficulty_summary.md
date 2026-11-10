# Old-set difficulty ablation

每个难度覆盖同样的 15 种攻击条件，domain 各 5 个；仅使用 old set。

Each difficulty group contains **n = 15 attack instances**, with **n_ER = 9** for ER. **N** denotes the number of distinct source tasks. Reused instances are averaged over three original-set runs; added instances are evaluated once. These are not three independent complete ablation runs.

## Gemini 3.7 Flash

| Difficulty | ASR (%, n=15) | ER (%, n=9) | Mean Score (n=15) |
|---|---:|---:|---:|
| easy | 40.00 | 70.37 | **1.0000** |
| medium | 44.44 | 74.07 | 0.7556 |
| hard | **46.67** | **88.89** | 0.5356 |

## DeepSeek Flash

| Difficulty | ASR (%, n=15) | ER (%, n=9) | Mean Score (n=15) |
|---|---:|---:|---:|
| easy | 46.67 | **77.78** | **0.7444** |
| medium | 48.89 | 74.07 | 0.6389 |
| hard | **53.33** | 62.96 | 0.4141 |


## 统计口径

- 每组 ASR/Score 对 15 种攻击条件等权平均，ER 仅对定义曝光的 9 种条件平均。无缺失评分、无补零。
- 原始实例按之前三轮结果逐实例取均值后复用；easy/medium/hard 各复用 9/3/3 个，其余新增 6/12/12 个各跑一次。不是仅统计新增实例，也没有按评测次数给复用实例更高权重。
- Gemini 的三轮为历史一次＋本机两次；DeepSeek 为本机三次，与前面的新旧 set 对比口径一致。历史 Gemini 的执行代码和 exposure 评估未验证与当前完全相同。
- 本机缺少部分历史 Gemini 原始 grades 文件，对应数值读取已保存的 `subset/model_results.json` 逐实例记录；没有把它们标记为本次重新核验的原始评分。
- 新增实例只有单轮，因此本表没有整套实验的三轮标准差；不能将原实例的三次复用当作三套独立的完整 ablation。
- 原始任务数量：easy=9、medium=3、hard=3。每组均为 15 个攻击实例，不能据此声称每组有 15 个独立原始任务。
- 两模型的任务得分均随难度升高而下降，ASR 均有所上升；ER 的变化方向不同。这是本轮描述性结果，不构成因果或显著性结论。

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

完整精度、逐实例来源，以及分别使用每一轮旧结果的敏感性汇总，见 `difficulty_summary.json`。
