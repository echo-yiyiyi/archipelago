# Gemini 3.7 Flash 与 DeepSeek V4.1 Flash：三次运行的均分与标准差

## English table for the rebuttal

**Table: Performance on the 15-task subset, reported as mean ± sample standard deviation across three runs per model.**

| Model | ASR (%, N = 15) | ER (%, N = 9) | Score (N = 15) |
|---|---:|---:|---:|
| Gemini 3.7 Flash | 44.44 ± 3.85 | 77.78 ± 19.25 | 0.8550 ± 0.0237 |
| DeepSeek V4.1 Flash | 48.89 ± 7.70 | 70.37 ± 12.83 | 0.6330 ± 0.0943 |

*Each model is summarized over R = 3 runs. Gemini 3.7 Flash includes the historical experiment and two current reruns; DeepSeek V4.1 Flash includes only the three current reruns. ASR (attack success rate) and Score (mean task score, 0–1) are computed over N = 15 tasks per run; ER (exposure rate) is computed over the nine tasks for which exposure is defined. Standard deviations are sample SDs (denominator R − 1); SDs for percentage-valued metrics are expressed in percentage points. The historical Gemini run and current reruns are not verified to use identical execution code and exposure evaluators.*

*Model identification: the runs used the official DeepSeek API with the legacy model ID `deepseek-v4-flash`. According to the [provider's model documentation](https://api-docs.deepseek.com/quick_start/pricing/), this ID is currently served by DeepSeek-V4.1-Flash-1017; it does not pin the original V4 Flash weights.*

## DeepSeek V4.1 Flash：三次有效重跑

| 运行 | 原任务均分（Mean Score） | ASR | ER |
|---|---:|---:|---:|
| 重跑 1：`deepseek_subset_be9eaed0c1eb` | 0.590000 | 53.33%（8/15） | 77.78%（7/9） |
| 重跑 2：`deepseek_subset_7f1d3b6710af` | 0.567778 | 40.00%（6/15） | 55.56%（5/9） |
| 重跑 3：`deepseek_subset_6b01a674aa46` | 0.741111 | 53.33%（8/15） | 77.78%（7/9） |

## Gemini 3.7 Flash：历史结果与两次有效重跑

| 运行 | 原任务均分（Mean Score） | ASR | ER |
|---|---:|---:|---:|
| 历史主实验 | 0.830556 | 46.67%（7/15） | 100.00%（9/9） |
| 重跑 1：`gemini37_subset_6ec42a2a10c8` | 0.856667 | 46.67%（7/15） | 66.67%（6/9） |
| 重跑 2：`gemini37_subset_d460da681561` | 0.877778 | 40.00%（6/15） | 66.67%（6/9） |

## 统计口径

- DeepSeek 仅统计上述三次本机有效重跑；Gemini 按要求统计历史主实验与上述两次本机有效重跑。所有启动失败的运行均不计入。
- 纳入的五次本机有效重跑均完成 15/15 个任务，任务进程退出码全部为 0。历史 Gemini 结果覆盖同一组 15 个任务。
- 样本标准差的分母为 n − 1（n = 3），计算对象为三次运行的汇总指标，不是 15 个任务之间的差异。
- 计算使用原始完整精度，展示值经过四舍五入。
- 重跑中观察到工具检查循环和未实际调用业务工具的情况；这些运行保留在统计中，未按表现筛除。因此，报告的波动包含实际执行过程中工具使用失败的影响。

## 数据来源

- [重跑 1 汇总](../../output/subset/deepseekv4/deepseek_subset_be9eaed0c1eb/score_summary.json)。
- [重跑 2 汇总](../../output/subset/deepseekv4/deepseek_subset_7f1d3b6710af/score_summary.json)。
- [重跑 3 汇总](../../output/subset/deepseekv4/deepseek_subset_6b01a674aa46/score_summary.json)。

- [Gemini 历史结果](model_results.json)：`Gemini 3.7 Flash`。
- [Gemini 重跑 1 汇总](../../output/subset/gemini37/gemini37_subset_6ec42a2a10c8/score_summary.json)。
- [Gemini 重跑 2 汇总](../../output/subset/gemini37/gemini37_subset_d460da681561/score_summary.json)。
