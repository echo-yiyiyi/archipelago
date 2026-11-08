# 重新筛选另外 15 个任务

此目录使用原来的 Gemini 分数和轮数作为参考，自动排除
附带 `previous_15_tasks.json` 中的全部旧任务。若本地有原始
`../../filter_task_difficulty/output/selected_15_tasks.json`，也会同时排除其中的任务。
原任务列表和原筛选脚本不会被修改。

每个候选**先跑 GPT 5.6 Sol，符合参考分桶才启动 Opus**；只有两者均符合才保留。
默认轮数限制、排序和配额沿用原筛选逻辑：

| 难度 | Gemini / GPT / Opus 的分数区间 | law | banking | consulting |
|---|---|---:|---:|---:|
| easy | score = 1 | 3 | 3 | 3 |
| medium | 0.75 ≤ score < 1 | 1 | 1 | 1 |
| hard | 0.5 ≤ score < 0.75 | 1 | 1 | 1 |

Gemini 候选要求 `30 < assistant turns < 100`，各桶按轮数从少到多尝试。
GPT/Opus 超过 80 个 assistant turns 记为 0 分，可以用
`--model-max-turns` 修改限制。实际给 agent 设置的 `HF_MAX_STEPS` 为限制加一。
没有人工补足选项；候选耗尽仍未满配额时返回非零状态，并保留部分结果。

## 先预览，不调用模型

从仓库根目录执行。新机器先安装 Docker 和 `uv`，并确保当前用户能使用 Docker，然后安装 Python 环境：

```bash
uv python install 3.13
uv venv --python 3.13 benchmark/rebuttal/more_tasks/.venv
uv pip install --python benchmark/rebuttal/more_tasks/.venv/bin/python \
  huggingface-hub httpx openai azure-identity azure-keyvault-secrets litellm==1.92.0
```

首次准备完成后激活并预览：

```bash
source benchmark/rebuttal/more_tasks/.venv/bin/activate
python benchmark/rebuttal/more_tasks/filter_more_tasks.py --prepare-only
```

预览不需要 Docker、API 凭据或数据集缓存。仓库已包含 `reference_candidates.json`
（218 个候选的原始 Gemini 分数、轮数和领域）和 `previous_15_tasks.json`
（旧任务排除列表），因此新机器不需要复制历史输出或轨迹。默认排除后有 203 个候选。
参考清单保存了原始 score summary 的 SHA-256，候选按原规则排序；如需从完整历史产物
重新计算，可显式传入 `--gemini-run /path/to/merged-gemini-3-5-flash`。
附带的清单只覆盖原始 `30 < turns < 100` 范围，更大的范围需要真实 Gemini run。

## API 配置

- GPT：默认使用本目录的 `orchestrator_config_gpt_azure.json`，部署名为
  `gpt-5.6-sol`，直接读取新资源的 `AZURE_API_KEY`，不再使用原 Key Vault。
  endpoint 为：

  ```text
  https://echoziyiyang-0462-resource.services.ai.azure.com/api/projects/echoziyiyang-0462/openai/v1/responses
  ```

  配置中的 `api_base` 去掉最后的 `responses`，完整保留项目路径。通过
  `openai/responses/gpt-5.6-sol` 兼容适配器请求此 Azure endpoint；这里的
  `openai/` 是 LiteLLM 协议适配器，不表示调用 OpenAI 官方服务。agent 和评分器
  都使用该 Azure Responses endpoint。可用 `--gpt-config /path/to/config.json`
  覆盖配置；原 Azure/Key Vault 配置仍可作为显式参数传入。

```bash
read -rsp 'Azure API key: ' AZURE_API_KEY; echo
export AZURE_API_KEY
```
- Opus 默认使用 **Anthropic 官方 API**，配置为本目录的
  `orchestrator_config_opus.json`，模型为 Claude Opus 5。设置 `ANTHROPIC_API_KEY` 即可，
  不需要 Azure Opus 部署或 endpoint。例如在终端安全输入密钥：

```bash
read -rsp 'Anthropic API key: ' ANTHROPIC_API_KEY; echo
export ANTHROPIC_API_KEY
```

官方接口地址固定为 `https://api.anthropic.com`。不要把密钥写入 JSON 或脚本。
`--opus-config /path/to/config.json` 可指定其他官方 Claude Opus 配置。

如需切回 Azure Foundry Opus，加 `--opus-provider azure`；脚本会改用本目录的
`orchestrator_config_opus_azure.json`，并读取：

```bash
export AZURE_AI_API_BASE='https://YOUR_RESOURCE.services.ai.azure.com/anthropic'
# 在 shell 或密钥管理器中安全设置 AZURE_AI_API_KEY；不要把密钥写入代码。
```

Azure 模式也可在 Opus JSON 中填写 `extra_args.api_base` 和 `azure_key_vault`（`vault_url`、
`secret_name`），或通过 `--opus-config` 指定其他配置。实际部署名不同需修改
配置中的模型名。凭据只传到子进程环境，不写入产物。

为兼容现有 agent 的 Claude 图片、空消息和缓存处理，运行时使用 LiteLLM
`anthropic/claude-opus-5` 适配器。默认发送到官方 API；Azure 模式下则显式指定
Foundry `/anthropic` endpoint 和 Azure 密钥。参考
[Microsoft Foundry Claude Messages API](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-claude)
和 [LiteLLM 自定义 Anthropic API base](https://docs.litellm.ai/docs/providers/anthropic)。

GPT 和 Opus 的新结果都使用 Azure Sol 评分。原来的 Gemini 结果仍用于参考分桶；旧评分器是
Gemini，切换评分器可能改变具体分数，但分桶、筛选配额和接受规则保持一致。

仅测试 Azure endpoint 和部署，不启动 Docker 或筛选：

```bash
python benchmark/rebuttal/more_tasks/check_azure.py
```

该命令实际发送一条小的 Responses 请求，输出成功状态和回复，不输出密钥。

## 正式运行

需要当前用户能访问 Docker；需要 `uv`、Python 3.13、Azure GPT 凭据和 Claude API key。
首次会同步 agent/grading 的锁定依赖并构建共享镜像：

```bash
source benchmark/rebuttal/more_tasks/.venv/bin/activate
python benchmark/rebuttal/more_tasks/filter_more_tasks.py
```

已有依赖和镜像时可加 `--skip-sync --skip-build`。如遇 Docker 的
`permission denied`，需先恢复当前用户的 Docker 访问权限；预览仍然可用。

正式运行会使用缓存的完整 `mercor/apex-agents/tasks_and_rubrics.json`，没有缓存则尝试
通过 Hugging Face 下载。可加 `--tasks-json /path/to/tasks_and_rubrics.json` 显式指定。
只有旧 15 个任务的数据集不足以产生新候选，会在模型运行前报错。

需要额外排除其他任务时重复添加 `--exclude-tasks /path/to/list.json`。
原 15 个始终排除。运行另一次独立筛选时，用新的 `--output-dir`，并额外排除本次的
`output/selected_15_tasks.json`。默认 `--base-port 19280`、
`--runtime-cidr 172.30.0.0/16`；可按机器端口和 Docker 网段情况覆盖。

## 输出和续跑

所有新输出位于本目录的 `output/`：

- `candidates.json`：排除旧任务后的候选及被跳过原因。
- `attempts.json` / `attempts.csv`：分模型结果、运行路径和当前配额。
- `selected_15_tasks.json`：已保留的新任务，包含 task_id、domain、turns、difficulty、prompt。
  筛选完成前此文件可能少于 15 个任务。
- `runs/`：每次模型运行的分数、trajectory、日志和任务产物。
- `driver_logs/`：筛选器启动的进程日志。
- `runtime/`：本次 agent/评分配置和到原代码的链接，不修改原配置。

每跑完一个模型就保存报告。启动、API、评分等基础设施失败会停止筛选，重新运行同一命令
即可续跑；GPT 已通过而 Opus 失败时只重试 Opus。Ctrl-C 后也可续跑。
已通过或明确被淘汰的候选不重复跑；模型配置、数据集、参考分数或排除规则改变时要求
新的输出目录，防止混合不同实验。一个输出目录同时只允许一个筛选进程。

## 离线测试

```bash
python -m unittest discover \
  -s archipelago/benchmark/rebuttal/more_tasks \
  -p 'test_filter_more_tasks.py' -v
```
