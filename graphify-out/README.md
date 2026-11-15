# graphify 知识图谱产物

本目录由 [graphify](https://github.com/safishamsi/graphify) 对**本仓库**全量静态分析生成，用于快速理解代码结构、模块边界与文档—代码对应关系。

## 文件说明

| 文件 | 用途 |
|---|---|
| `graph.html` | 交互式图谱，浏览器直接打开，无需服务器。支持搜索、缩放、按社区筛选 |
| `graph.json` | 机器可读图谱（node-link 格式），可做 GraphRAG、Neo4j 导入或二次分析 |
| `GRAPH_REPORT.md` | 审计报告：语料统计、核心节点、意外连接、社区划分、知识缺口、建议问题 |
| `.graphify_labels.json` | 87 个社区的人工命名映射 |
| `manifest.json` | 每个源文件的抽取指纹，供 `graphify --update` 增量复用 |
| `cost.json` | 抽取过程的 token 记账 |

`cache/` 为本地抽取缓存（可由源码重建），不入版本库。

## 本次构建概览

- 语料：169 个文件 / 约 68k 词（120 代码、26 文档、23 截图）
- 图谱：**1615 节点 / 4221 边 / 87 社区**
- 抽取置信度：81% EXTRACTED（源码中显式可见）、19% INFERRED（结构化推断），0% AMBIGUOUS
- 核心枢纽：`OptimizePage`(68 边)、`MainWindow`(55)、`RecordTable`(41)、`LoopService`(38)、`train()`(36)

## 重新生成

```bash
pip install graphifyy
graphify .            # 在本仓库根目录执行
graphify export html
```

## 已知局限

- **路径已归一化。** 图谱最初是在包含本仓库的父目录上构建的，`source_file` 带有 `Industrial-RAC-HPO-main/` 前缀。发布前已统一去除该前缀，使其与本仓库布局一致；`GRAPH_REPORT.md` 中的引用路径也做了同样处理。
- **706 条边在构建时被丢弃**（悬空端点），主要来自 23 张截图分块的跨分块引用；另有 4 条自环、约 100 条同端点边折叠。因此**图片区域的连边密度偏低**，不能据此判断截图之间的真实关联强度。
- **token 记账为 0。** 本次语义抽取由宿主代理的并行子任务完成，用量未回传，`cost.json` 中的数字不代表真实开销。
- 图谱只反映**静态结构**，不包含运行时行为、性能特征或真实实验结论；算法可靠性请以 `docs/` 下的交付报告为准。
