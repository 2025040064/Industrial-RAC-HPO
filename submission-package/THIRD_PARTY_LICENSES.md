# 第三方开源组件与许可证声明

本项目主体代码（`src/`、`official_submission/`、`tests/`、`scripts/`）采用 **Apache License 2.0** 授权，全文见仓库根目录 `LICENSE`。

以下为本项目直接依赖的第三方组件及其许可证。所有组件均通过 `requirements-contest.txt` / `requirements-contest-sampler.txt` 固定版本，运行时不联网安装。

## 一、竞赛运行时依赖（requirements-contest.txt）

| 组件 | 版本 | 许可证 | 用途 |
|---|---|---|---|
| numpy | 1.26.4 | BSD-3-Clause | 数值计算、数组运算 |
| optuna | 4.5.0 | MIT | TPE 采样器、超参数搜索框架 |
| scikit-learn | 1.7.2 | BSD-3-Clause | ExtraTrees 代理模型、Ridge、GP 等 |
| scipy | 1.16.3 | BSD-3-Clause | 统计检验（Spearman 秩相关等） |

## 二、决策采样器依赖（requirements-contest-sampler.txt）

| 组件 | 版本 | 许可证 | 用途 |
|---|---|---|---|
| pytrio | 0.2.9 | 平台提供（PyTRIO SDK） | 平台决策服务客户端 |
| transformers | 5.23.0 | Apache-2.0 | LoRA 采样器推理 |
| modelscope | 1.40.3 | Apache-2.0 | 模型权重下载与管理 |

## 三、基础模型

| 组件 | 版本 | 许可证 | 用途 |
|---|---|---|---|
| Qwen/Qwen3.5-4B | — | Apache-2.0（通义千问开源协议） | 决策采样器基座模型（平台允许列表内） |

## 四、平台提供、非开源组件

| 组件 | 说明 |
|---|---|
| contest_harness（Harness SDK） | 由竞赛平台提供，用于容器内运行调度与回调，非本项目打包内容 |
| 平台隐藏测试集 | 由竞赛平台持有，本项目**不包含**任何隐藏测试数据 |

## 五、合规声明

1. 本包**不包含**账号、密钥、Token 或任何凭证（`~/.pytrio/config.toml` 等不在包内）。
2. 本包**不包含**平台隐藏测试集或其派生标签。
3. 本包**不包含**违规离线拟合产物；所有候选模型均由平台容器内基于合法父检查点续训产生。
4. 原始数据来源见 `datasets/OFFICIAL_COMPETITION_SOURCES.md`，均为公开数据集（UCI Steel Energy、CNC Milling 2025 等）。
5. 未修改平台锁定模型架构与输入 schema；依赖清单未引入 `torch` 等平台禁止项。

---

生成日期：2026-11-25
