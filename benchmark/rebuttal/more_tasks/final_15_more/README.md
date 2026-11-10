# 新增 15 个攻击实例

输入为 `../results/selected_15_tasks.json`。按原 subset 的 S01–S15 顺序，
从相同 domain/difficulty 桶取新清单中第一个未使用的任务；每个任务只用一次。
逐项保留 goal、vector、leakage_type、add_user_prompt、no_key_words 和
user_allow_additional_instruction。完整对应关系在 `generation_manifest.json`。

模型仍为 GPT 5.6 Sol，按用户要求使用新的 Azure 部署 `gpt-5.6-sol` 和项目 endpoint：

```text
https://echoziyiyang-0462-resource.services.ai.azure.com/api/projects/echoziyiyang-0462/openai/v1/responses
```

keyword、attack config、载体文件、watcher、ELF/PYC 编译都调用原 benchmark 模块。
重新从新任务 prompt 提取 3–4 个 keyword，并重新生成配置和素材。
dynamic 和 suffix 的 `no_key_words` 开关与 subset 一致。
没有复制旧任务的 attack config 或素材。未指定 reasoning effort，沿用原生成器默认行为。

## 生成与续跑

从仓库根目录运行，使用已有 `agents/.venv`，并确保 Docker 可用。
生成器读取仓库根目录被 Git 忽略的 `.env` 中的 `AZURE_API_KEY`；凭据不会写入产物。
也支持环境变量 `AZURE_OPENAI_API_KEY`，无直接 key 时保留原 Key Vault 凭据流程。

```bash
agents/.venv/bin/python benchmark/rebuttal/more_tasks/generate_final_15_more.py
```

keyword 支持续跑，每完成一个任务保存 `generated_Sxx.json`。
重跑复用已通过校验的 checkpoint；失败任务重新生成。请勿同时启动多个生成进程。
输入或生成设置改变时，要求使用新的 `--output-dir`，避免混合实验。

`--prepare-only` 仅准备映射和生成输入；`--validate-only` 检查完整生成结果。
最终合并文件为 `selected_15_tasks_with_attack_config.json`，
只有全部任务生成后才写入；`generation_complete.json` 记录完成时间和内容摘要。

## 多模型运行和 judge

使用已有模型配置，例如：

```bash
agents/.venv/bin/python benchmark/rebuttal/more_tasks/run_final_15_more.py \
  --model deepseekv4 --concurrency 15 --skip-build

agents/.venv/bin/python benchmark/rebuttal/more_tasks/run_final_15_more.py \
  --model gemini37 --concurrency 15 --skip-build
```

加 `--dry-run` 可在校验完整素材后打印运行命令。更换 `--model` 使用
`benchmark/orchestrator_config_<model>.json` 或 `litellm_configs/<model>.json`。
结果分模型保存在 `benchmark/output/final_15_more/<model>/<run-id>/`。
运行调用原 `run_concurrency.sh` / `main_concurrency.py`，包含任务评分、攻击成功检查和
适用实例的 exposure judge。模型及评分器凭据要求与原 subset 相同；生成 Azure key
不会自动替换原实验评分器。默认 security/exposure 的 LLM judge 为原有 Gemini 3.6 Flash。

也可直接把本目录的最终 JSON 传给原 runner 的 `--task-json`。
本目录内素材使用相对路径，生成结果可整体搬移，无需依赖旧 subset 的素材软链接。

## 离线检查

```bash
agents/.venv/bin/python -m unittest discover -s benchmark/rebuttal/more_tasks \
  -p test_generate_final_15_more.py -v

agents/.venv/bin/python benchmark/rebuttal/more_tasks/generate_final_15_more.py --validate-only
```

验证包括逐项匹配、keyword 数量、judge 配置加载、runner 识别全部 15 个任务、
素材路径完整性及 watcher 配置一致性。静态验证不表示已经运行受测模型或取得攻击成功率。
