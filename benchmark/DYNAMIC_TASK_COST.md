# Dynamic benchmark estimated API cost per task

## Audit correction: recorded main-agent calls only

These figures are estimates for recorded main-agent responses, not reconciled
account bills. All 150 canonical trajectories were checked: sums of each
call_log's input, output, cache-read and cache-write fields equal the top-level
usage counters. Multi-turn input and output are therefore already accumulated.

The summarization implementation makes additional model calls without tracking
their usage in the agent's UsageTracker. Recorded compaction counts across 30
tasks are Sol 0, GLM 8, DeepSeek 17, Gemini 1, and Kimi 1. Historical trajectories
in this group contain no summarization_records, so those extra token charges
cannot be recovered exactly from these trajectory files. Grading calls, security
judge calls, other batches/retries, and any provider-billed requests that did not
return usage are also outside these figures. These are possible differences
from account bills; actual reconciliation requires a billing period and export.

The earlier statement that GLM-5.3-Flash had no published price was incorrect.
A fresh read of the official page gives the rates used below.

Pricing checked on September 6, 2026. Costs are in USD and use the average
token usage in `DYNAMIC_TOKEN_USAGE.md`. The five canonical models use 30 tasks
each (8 dynamic prompt + 11 script allow + 11 script no-allow). Opus uses the
separate 10-task historical sample because its canonical run is incomplete.

The calculation is:

```text
cost = (uncached input × input rate
      + cached input × cached-input rate
      + cache-write input × cache-write rate
      + output × output rate) / 1,000,000
```

Cached and cache-write tokens are subsets of total input. The canonical runs
reported zero cache-write tokens. The Opus sample did report cache writes, so
those tokens are charged at the separate five-minute cache-write rate.

## Estimated average cost

| Model | Usage sample | Estimated cost/task | Pricing treatment |
|---|---:|---:|---|
| GPT-5.6 Sol | 30 tasks | **$0.633** | Current standard promotional API rates; no call exceeded the 272K long-context threshold |
| GLM-5.3-Flash | 30 tasks | **$0.0295** | Current promotional rate; list-rate estimate $0.0590 |
| DeepSeek-V4-Flash | 30 tasks | **$0.078** | Off-peak rates; selected runs occurred on Sunday |
| Gemini-3.5-Flash | 30 tasks | **$1.690** | Vertex AI Standard, Global endpoint |
| Kimi-K3 | 30 tasks | **$0.520** | Standard Kimi API rates |
| Claude Opus 5 | 10-task sample | **$1.428** | Standard Claude API rates, including five-minute cache writes |

DeepSeek's corresponding peak-rate estimate is **$0.156/task**. Its official
peak rates are exactly twice its off-peak rates.

## Rates used (USD per 1M tokens)

| Model | Uncached input | Cached input | Cache write | Output | Official source |
|---|---:|---:|---:|---:|---|
| GPT-5.6 Sol | $4.00 | $0.40 | $5.00 | $20.00 | [OpenAI model page](https://developers.openai.com/api/docs/models/gpt-5.6-sol), [Microsoft Foundry announcement](https://azure.microsoft.com/en-us/blog/gpt-5-6-now-available-in-microsoft-foundry/) |
| GLM-5.3-Flash (promotion) | $0.075 | $0.015 | N/A | $0.25 | [Z.AI pricing](https://docs.z.ai/guides/overview/pricing) |
| DeepSeek-V4-Flash, off-peak | $0.22 | $0.007 | N/A | $0.66 | [DeepSeek Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/) |
| DeepSeek-V4-Flash, peak | $0.44 | $0.014 | N/A | $1.32 | [DeepSeek Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/) |
| Gemini-3.5-Flash, Standard Global | $1.50 | $0.15 | N/A | $9.00 | [Google Cloud Vertex AI pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing) |
| Kimi-K3 | $3.00 | $0.30 | N/A | $15.00 | [Official Kimi K3 announcement](https://forum.moonshot.ai/t/kimi-k3-is-here-our-most-capable-model/480) |
| Claude Opus 5 | $5.00 | $0.50 | $6.25 (5 min) | $25.00 | [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing), [Opus 5 announcement](https://www.anthropic.com/news/claude-opus-5) |

The OpenAI cache-write rate is shown for completeness, but the selected Sol
trajectories reported zero cache-write tokens. Azure contract discounts,
regional multipliers, taxes, and non-token tool charges are not included.

## GLM-5.3-Flash pricing correction

Z.AI's [official pricing page](https://docs.z.ai/guides/overview/pricing)
lists GLM-5.3-Flash at $0.075 input, $0.015 cached input, and $0.25 output
per million tokens during its promotion, ending September 9, 2026 at 24:00
UTC+8. List rates are $0.15 / $0.03 / $0.50 respectively. The recorded
main-agent average is $0.02951227 at promotional rates or $0.05902454 at list
rates. These replace the earlier unrelated-model proxy estimates.

## Calculation inputs

| Model | Avg total input | Avg cached input | Avg cache write | Avg output |
|---|---:|---:|---:|---:|
| GPT-5.6 Sol | 463,769 | 376,592 | 0 | 6,664 |
| GLM-5.3-Flash | 748,089 | 607,104 | 0 | 39,327 |
| DeepSeek-V4-Flash | 1,836,833 | 1,690,176 | 0 | 51,668 |
| Gemini-3.5-Flash | 3,106,569 | 2,572,242 | 0 | 55,826 |
| Kimi-K3 | 427,575 | 366,959 | 0 | 15,219 |
| Claude Opus 5 sample | 502,708 | 345,195 | 73,364 | 15,064 |

For Opus, average base uncached input after removing cache hits and cache
writes is 84,149 tokens. For the other models, uncached input is total input
minus cached input.
