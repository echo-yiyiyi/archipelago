# all_category_test

从 `../final_benchmark` 抽取 24 个任务：普通类别各 4 个，子类别各 2 个。

在每个 batch 内枚举组合，优先使 inject_vector 分布均匀，再减少 inject_goal 重复；随后使用固定种子 42 的多起点协调搜索，减少跨 batch 的 goal、vector 及原任务重复。动态脚本 true/false 组保持相同任务，对优化统计只计一组。不保证全局最优。

| 类别 | 数量 | vector 分布 | 不同 goal 数 |
| --- | ---: | --- | ---: |
| static_prompt_injection | 4 | {'email': 1, 'calendar': 1, 'md': 1, 'xlsx': 1} | 4 |
| static_script_injection | 4 | {'py': 2, 'elf': 1, 'pyc': 1} | 4 |
| user_prompt_script_swap/args | 2 | {'elf': 1, 'pyc': 1} | 2 |
| user_prompt_script_swap/no_args | 2 | {'py': 1, 'pyc': 1} | 2 |
| user_prompt_suffix_plant | 4 | {'py': 1, 'elf': 2, 'pyc': 1} | 4 |
| dynamic_prompt_injection | 4 | {'dynamic_prompt_injection': 4} | 4 |
| dynamic_script_injection/allow_additional_instruction_true | 2 | {'dynamic_script_execution': 2} | 2 |
| dynamic_script_injection/allow_additional_instruction_false | 2 | {'dynamic_script_execution': 2} | 2 |

共覆盖 22 个不同 goal。抽样任务和完整分布见 `manifest.json`。原配置、相对路径及配套文件均保留，源数据未修改。
