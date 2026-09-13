# direct_arg

与 `../with` 的 10 个任务逐条配对，task、goal、attack config、恢复 ELF、watcher 代码和辅助文件保持一致。仅各任务 `dynamic_watcher_config.json` 的 `instruction_template` 改变：损坏文件直接展示完整的两个参数调用示例，并说明第二个参数需要的任务信息。仍然保持 `user_allow_additional_instruction=false`，不创建 additional instruction TXT。

参数说明从现有 ELF 内嵌 Python 的 `ARGUMENT_HELP` 静态提取，不执行攻击脚本、不重新生成 payload。示例使用占位值，实际值由 agent 从任务中获取。读取一个损坏文件后恢复其他文件，以及成功 recover 后恢复文件的行为沿用 `with`。

恢复入口只接受两个非空参数。goal 16 的多个邮箱必须合并为一个带引号的参数；goal 32 当前恢复脚本只支持一个源文件路径，因此这里修正原报错中多路径示例的歧义。goal 13 支持单个附件路径，或作为一个参数传入的带引号 JSON 路径数组。上述修正仅修改提示，不修改 ELF。

在仓库根目录重建与验证：

```bash
python3 benchmark/final_benchmark/ablation/watcher_script/build_direct_arg.py
python3 benchmark/final_benchmark/ablation/watcher_script/test_direct_arg.py
```

验证覆盖 10 对任务的文件差异、实际 watcher 写入内容、含空格和单引号的原文件路径，以及示例参数通过真实 recovery 参数检查（隔离提取参数检查函数，mock socket validation，不运行攻击）。未运行模型评测。
