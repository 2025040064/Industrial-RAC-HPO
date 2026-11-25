# 比赛数据集官方来源（A / B / C）

记录日期：2026-11-24。链接由用户于同日提供，并在当日逐一访问核验。以下三个 URL 是比赛三任务的**官方来源入口**；历史文档中出现的其他域名按"对应关系"处理，不覆盖历史原文。

## A 气体识别 — UCI Gas Sensor Array Drift

- **官方链接**：https://archive.ics.uci.edu/dataset/224/gas
- **直接下载**：https://archive.ics.uci.edu/static/public/224/gas+sensor+array+drift+dataset.zip （页面标注 9.5 MB）
- **页面核验**：数据集编号 224；页面写 13,910 条测量、16 个化学传感器、6 种纯气体（Ammonia、Acetaldehyde、Acetone、Ethylene、Ethanol、Toluene）；每条记录由 8 个特征 × 16 通道组成 128 维向量；数据按 10 个 batch 组织（按月份合并）。
- **DOI / 许可**：10.24432/C5RP6W；CC BY 4.0。
- **与项目记录的关系**：与 `RAC-HPO_项目文档总汇.md` 中 A 任务的来源链接一致。平台按特征编号 1–128 排序，`inputs.features` 为长度 128 数组。

## B 轴承剩余寿命 — XJTU-SY Bearing Datasets

- **官方链接（GitHub README）**：https://github.com/WangBiaoXJTU/xjtu-sy-bearing-datasets/blob/master/README.md
- **页面核验**：由西安交通大学设计科学与基础部件研究所与长兴 Sumyoung 科技提供，15 个滚动轴承的完整 run-to-failure 加速退化试验数据；公开可用于验证轴承剩余寿命预测算法。
- **官方 README 列出的下载入口**：作者网站 http://biaowang.tech 、Google Drive、Dropbox、MediaFire、MEGA、百度网盘。
- **引用要求**：Wang B., Lei Y., Li N., Li N., "A Hybrid Prognostics Approach for Estimating Remaining Useful Life of Rolling Element Bearings", IEEE Transactions on Reliability, 69(1):401-412, 2020, DOI 10.1109/TR.2018.2882682。
- **与项目记录的关系**：`src/rac_hpo/data/industrial/local.py` 与历史文档使用 `https://biaowang.tech/xjtu-sy-bearing-datasets/`，这是官方 README 列出的作者网站入口，**不是错误链接**；GitHub README 是更权威的说明页，本清单以它为准。预测目标是距离该轴承最后记录时刻的剩余寿命（分钟），按物理轴承隔离。

## C 发动机剩余寿命 — NASA C-MAPSS

- **官方链接（data.gov 目录页）**：https://catalog.data.gov/dataset/cmapss-jet-engine-simulated-data
- **发布方**：NASA PCoE；页面最近检查 2026-06-16，数据最后更新 2025-05-29。
- **页面核验**：多变量时间序列，每个数据集分 train/test；每条序列来自一台不同发动机。FD001（100/100 条轨迹，1 工况，1 故障模式）、FD002（260/259，6 工况，1 故障）、FD003（100/100，1 工况，2 故障）、FD004（248/249，6 工况，2 故障）。zip 文本为 26 列空格分隔：第 1 列单元号、第 2 列循环数、第 3–5 列工况设置、第 6–26 列传感器测量。
- **与项目记录的关系**：历史文档使用 `https://data.nasa.gov/dataset/cmapss-jet-engine-simulated-data`（同数据集的旧 NASA 域名）；本清单以用户提供的 catalog.data.gov 目录页为准。预测目标为剩余运行循环数（cycles），回归不封顶、不分箱，不以发动机编号/循环编号/最终寿命作为特征。

## 使用边界（不可越界）

1. 平台隐藏测试数据、标签和发动机/轴承名单**不随上述官方包分发**；公开数据与隐藏测试不能作为同集前后对照。
2. 官方包的下载归档 SHA-256 与下载日期：`unknown`（尚未在本仓库中留存原始归档；下载后在此处追加，不要推测）。
3. 原始归档默认不纳入 Git（`.gitignore` 忽略 `datasets/raw/`）；仅记录来源、日期与哈希。
4. A 的 128 维特征、B 的两通道 32,768 点/分钟快照、C 的 3 设置 + 21 传感器等任务口径，以平台任务包为准；本清单只记录公开来源事实。
