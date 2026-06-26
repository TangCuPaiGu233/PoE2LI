# Phase 2 数据管道脚本化对齐纪要（草案）

> 状态：草案，待松烟确认  
> 创建人：守夜  
> 时间：项目时间 第 7 天 07:21

## 一、目标

将 GGPK 导出 → 数据入库 → 知识图谱构建 编排为可重复工作流。

## 二、建议分工

| 模块 | 负责人 | 边界 |
|------|--------|------|
| GGPK 导出（EN/TC/SC） | 守夜 | `export_en_tc.py`、`extract_sc.py`、`fill_tc_from_sc.py`、TC 补齐逻辑 |
| 数据导入入库 | 松烟 | `import_game_data.py`、`GameDatum` 模型、入库校验、`--validate` 报告 |
| 知识图谱实体/边入库 | 松烟 | `game_relations.json` 解析、`kb_entities/kb_edges` 入库、实体解析 |
| Pipeline 编排 | 松烟 | `run_pipeline.py`、调度、CI/CD 接入 |
| PyPoE 兼容性 | 远岫 | `export_en_tc.py` 的 bundle/spec 问题诊断 |

## 三、依赖清单与阻塞项

### 3.1 已就绪
- TC 356 文件补齐完成，P0 全覆盖
- `fill_tc_from_sc.py` 可用
- `verify_data_completeness.py` 可用
- Pipeline MVP 已合入 main

### 3.2 阻塞项
- PyPoE TC override 打包问题：`export_en_tc.py` 仍无法从 GGPK 直接导出缺失 TC；待远岫诊断结论
- `game_relations.json`：当前主工作区存在，但知识图谱入库侧由松烟负责
- `entity_icons.json`：当前为空，纳入松烟 knowledge ingest 范围

### 3.3 待确认
- Phase 2 pipeline 编排入口是 `run_pipeline.py` 还是新增入口？
- 知识图谱实体解析是否依赖 `resolve_relations.py`？
- SC → TC fallback 是否纳入 Phase 2 自动化流程？

## 四、下一步

- 松烟确认分工边界
- 朝露确认 Phase 2 优先级
- 远岫输出 PyPoE 诊断结论
