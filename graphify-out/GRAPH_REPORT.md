# Graph Report - EmbodiedIntelligence  (2026-11-09)

## Corpus Check
- 169 files · ~68,166 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 18 file(s) not represented in the graph (top: (none) 12, .cmd 2, .command 2)

## Summary
- 1615 nodes · 4221 edges · 87 communities (64 shown, 23 thin omitted)
- Extraction: 81% EXTRACTED · 19% INFERRED · 0% AMBIGUOUS · INFERRED: 792 edges (avg confidence: 0.87)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- GUI 优化页集成测试
- 代理模型与指标单元测试
- 工作区组件与集成测试
- 离线闭环服务与并发
- RAC-HPO 架构设计文档
- 工业页 GUI 集成测试
- 工业基准服务与脚本
- Windows 启动回归测试
- Agent 协作约定
- CNC 流水线集成测试
- 数据审计与切分校验
- GUI 图表与工作区状态
- GUI 页面骨架
- GUI 主题与主窗口
- 弱项复现与配置持久化
- 数据加载与清单校验
- 数据页与辅助工作区
- Phase 3 界面截图
- 鲁棒目标与分类阈值
- 分类优化流程
- training lightgbm trainer
- test environment snapshot
- test optimization test
- step3 optimize search
- interfaces gui main
- test industrial data
- data cnc milling
- test summary alignment
- interfaces gui charts
- phase1 comparison
- test workspace lifecycle
- interfaces gui pages
- data industrial common
- test industrial benchmark
- step1 data
- data loop views
- industrial ai4i 2020
- data industrial uci
- interfaces gui pages
- interfaces gui sidebar
- interfaces gui pages
- training classification estimator
- industrial algorithm optimization
- algorithm guide regime
- controlled loop report
- infrastructure database experimentrepository
- evaluation classification rationale
- test gui test
- sidebar collapse ui
- data industrial common
- configs default data
- summary alignment benchmark
- interfaces gui workers
- training model export
- configs default feature
- datasets industrial sources
- ui workbench v2
- interfaces gui workspace
- industrial training report
- sidebar mid animation
- interfaces gui workbench
- training classification classificationmodel
- datasets sources
- interfaces gui widgets
- configs default lambda
- configs default learning
- configs default model
- test workbench v2
- test atomic retry
- configs default min
- configs default num
- configs default optimization
- configs default robustness
- interfaces gui workspace
- ui design no
- user manual classification
- pkg industrial rac

## God Nodes (most connected - your core abstractions)
1. `OptimizePage` - 68 edges
2. `MainWindow` - 55 edges
3. `RecordTable` - 41 edges
4. `LoopService` - 38 edges
5. `train()` - 36 edges
6. `optimize()` - 34 edges
7. `ApplicationService` - 30 edges
8. `IndustrialService` - 29 edges
9. `TaskCancelled` - 29 edges
10. `atomic_text()` - 27 edges

## Surprising Connections (you probably didn't know these)
- `test_industrial_worker_reports_real_missing_data_and_keeps_old_pages()` --uses--> `MainWindow`  [INFERRED]
  tests/integration/test_industrial_gui.py → src/rac_hpo/interfaces/gui/main_window.py
- `test_nonfinite_values_display_unknown()` --calls--> `format_value()`  [INFERRED]
  tests/integration/test_workbench_v2.py → src/rac_hpo/interfaces/gui/widgets.py
- `test_recorded_time_offsets_are_respected()` --calls--> `display_time()`  [INFERRED]
  tests/integration/test_workbench_v2.py → src/rac_hpo/interfaces/gui/workspace_state.py
- `test_metric_breakpoint_uses_available_width_without_empty_columns()` --uses--> `MetricsGrid`  [INFERRED]
  tests/integration/test_workspace_widgets.py → src/rac_hpo/interfaces/gui/workspace_widgets.py
- `test_observation_selection_and_hidden_selection_are_independent()` --uses--> `RecordTable`  [INFERRED]
  tests/integration/test_workbench_v2.py → src/rac_hpo/interfaces/gui/workspace_widgets.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **RAC-HPO 搜索机制：固定 J + 代理门槛 + 可信权重 + TPE 回退** — industrial_rac_hpo_main_architecture_rac_hpo, industrial_rac_hpo_main_architecture_fixed_j, industrial_rac_hpo_main_architecture_surrogate_gate, industrial_rac_hpo_main_architecture_trusted_regime_weight, industrial_rac_hpo_main_architecture_tpe_fallback [EXTRACTED 1.00]
- **受控单轮闭环组件集合** — industrial_rac_hpo_main_architecture_loop_service, industrial_rac_hpo_main_architecture_loop_views, industrial_rac_hpo_main_architecture_loop_repository, industrial_rac_hpo_main_architecture_drift_monitor, industrial_rac_hpo_main_plan_controlled_loop_protocol [EXTRACTED 1.00]
- **工作台展示契约：状态、稳定 ID、平行坐标与不排名** — industrial_rac_hpo_main_ui_design_workspace_view_state, industrial_rac_hpo_main_ui_design_trial_stable_id, industrial_rac_hpo_main_ui_design_parallel_coordinates, industrial_rac_hpo_main_ui_design_no_ranking_across_runs [INFERRED 0.85]
- **RAC-HPO 决策循环（代理→前向检查→候选→成本采集）** — industrial_rac_hpo_main_docs_algorithm_guide_fixed_robust_objective_j, industrial_rac_hpo_main_docs_algorithm_guide_extratrees_surrogate, industrial_rac_hpo_main_docs_algorithm_guide_surrogate_forward_quality_check, industrial_rac_hpo_main_docs_algorithm_guide_candidate_pool_generation, industrial_rac_hpo_main_docs_algorithm_guide_cost_aware_acquisition, industrial_rac_hpo_main_docs_algorithm_guide_trusted_regime_priority_q [EXTRACTED 1.00]
- **受控单轮闭环的治理组件（门禁/租约/生命周期库/人工切换）** — industrial_rac_hpo_main_docs_controlled_loop_one_shot_gate, industrial_rac_hpo_main_docs_controlled_loop_lifecycle_database, industrial_rac_hpo_main_docs_controlled_loop_process_lease_recovery, industrial_rac_hpo_main_docs_controlled_loop_manual_promotion_rollback, industrial_rac_hpo_main_docs_controlled_loop_report_acceptance_run_record [INFERRED 0.85]
- **工业数据来源审计簇（独立适配器+哈希+固定划分）** — industrial_rac_hpo_main_datasets_industrial_sources_ai4i_2020_dataset, industrial_rac_hpo_main_datasets_industrial_sources_secom_dataset, industrial_rac_hpo_main_datasets_industrial_sources_paderborn_bearing_dataset, industrial_rac_hpo_main_datasets_industrial_sources_sha256_provenance_audit, industrial_rac_hpo_main_datasets_industrial_sources_local_normalized_table_contract [EXTRACTED 1.00]
- **RAC-HPO 搜索闭环（代理 → 前向验证 → 可信工况 → 候选排序 → 回退）** — industrial_rac_hpo_main_docs_phase_2_3_report_extra_trees_surrogate, industrial_rac_hpo_main_docs_phase_2_3_report_forward_validation_gate, industrial_rac_hpo_main_docs_phase_2_3_report_bounded_regime_priority, industrial_rac_hpo_main_docs_phase_2_3_report_acquisition_score, industrial_rac_hpo_main_docs_phase_2_3_report_tpe_fallback [EXTRACTED 1.00]
- **无泄漏评估纪律（固定时间划分 + 分组划分 + 封存测试 + 八条防泄漏规则）** — industrial_rac_hpo_main_docs_phase_0_1_report_whole_day_time_split, industrial_rac_hpo_main_docs_phase_0_1_report_sealed_test_set_protocol, industrial_rac_hpo_main_docs_phase_0_1_report_date_group_not_independent_batch, industrial_rac_hpo_main_docs_phase_2_3_report_tool_group_stratified_split, industrial_rac_hpo_main_docs_rac_hpo_implementation_architecture_v1_leakage_prevention_rules [INFERRED 0.85]
- **阶段化交付与跨平台验证链（总纲路线图 → 阶段 0/1 → 阶段 2/3 → macOS 验证）** — industrial_rac_hpo_main_docs_rac_hpo_implementation_architecture_v1_phased_roadmap, industrial_rac_hpo_main_docs_phase_0_1_report_delivery_report, industrial_rac_hpo_main_docs_phase_2_3_report_delivery_report, industrial_rac_hpo_main_docs_mac_setup_report_macos_verification_record [INFERRED 0.75]
- **折叠侧边栏交互与动效设计族** — industrial_rac_hpo_main_docs_sidebar_collapse_ui_collapsingsidebar, industrial_rac_hpo_main_docs_sidebar_collapse_ui_overlay_layout, industrial_rac_hpo_main_docs_sidebar_collapse_ui_navigationdelegate, industrial_rac_hpo_main_docs_sidebar_collapse_ui_antiflicker_strategy, industrial_rac_hpo_main_docs_sidebar_collapse_ui_reduced_motion_support [EXTRACTED 1.00]
- **回归搜索方法组合（Grid / 资源剪枝 / RAC 门禁 / 暖启动）** — industrial_rac_hpo_main_docs_summary_alignment_grid_search, industrial_rac_hpo_main_docs_summary_alignment_successive_halving_hyperband, industrial_rac_hpo_main_docs_summary_alignment_rac_proxy_gate, industrial_rac_hpo_main_docs_user_manual_rac_warm_start, industrial_rac_hpo_main_docs_user_manual_regression_workflow [INFERRED 0.85]
- **优化页可视化组件面（图表面板/抽屉/平行坐标/曲线缓存）** — industrial_rac_hpo_main_docs_ui_refactor_report_optimization_chart_panels, industrial_rac_hpo_main_docs_ui_refactor_report_detail_drawer, industrial_rac_hpo_main_docs_ui_workbench_v2_report_parallel_coordinates, industrial_rac_hpo_main_docs_ui_workbench_v2_report_curve_cache [INFERRED 0.75]
- **工业实验：配置 → 训练/搜索 → 指标与日志观测** — industrial_rac_hpo_main_docs_images_industrial_training_search_config, industrial_rac_hpo_main_docs_images_industrial_classification_metrics_panel, industrial_rac_hpo_main_docs_images_logs_task_event_log_stream [INFERRED 0.85]
- **离线闭环会话：预算协议 → 回放回收 → 模型槽位 → 人工确认** — industrial_rac_hpo_main_docs_images_loop_session_protocol_and_budget, industrial_rac_hpo_main_docs_images_loop_replay_measurement_mode, industrial_rac_hpo_main_docs_images_loop_session_model_slots_panel, industrial_rac_hpo_main_docs_images_loop_human_in_the_loop_confirmation [EXTRACTED 1.00]
- **三工作台职能分工：工业训练 / 运行日志 / 自主优化** — industrial_rac_hpo_main_docs_images_industrial_industrial_training_page, industrial_rac_hpo_main_docs_images_logs_run_log_live_session_page, industrial_rac_hpo_main_docs_images_loop_autonomous_offline_loop_page [INFERRED 0.85]
- **Phase 1 五屏贯通工作流：数据管理 → 模型训练 → 超参数优化 → 实验对比 → 运行日志** — industrial_rac_hpo_main_docs_images_phase1_data, industrial_rac_hpo_main_docs_images_phase1_training, industrial_rac_hpo_main_docs_images_phase1_optimization, industrial_rac_hpo_main_docs_images_phase1_comparison, industrial_rac_hpo_main_docs_images_phase1_logs [INFERRED 0.95]
- **实验血缘链：数据集 → 固定划分 → LightGBM 基线 → TPE 鲁棒搜索实验 → 对比表** — industrial_rac_hpo_main_docs_images_phase1_data_uci_steel_energy_851, industrial_rac_hpo_main_docs_images_phase1_data_fixed_time_split, industrial_rac_hpo_main_docs_images_phase1_training_lightgbm_baseline, industrial_rac_hpo_main_docs_images_phase1_optimization_experiment_aa07ddc49e84119, industrial_rac_hpo_main_docs_images_phase1_comparison_experiment_history_table [EXTRACTED 1.00]
- **同口径四算法对照：baseline / random / tpe / tpe_robust（同固定划分与预算）** — industrial_rac_hpo_main_docs_images_phase1_training_lightgbm_baseline, industrial_rac_hpo_main_docs_images_phase1_comparison_random_search, industrial_rac_hpo_main_docs_images_phase1_optimization_tpe_robust, industrial_rac_hpo_main_docs_images_phase1_comparison_experiment_history_table [EXTRACTED 1.00]
- **RAC-HPO 实验流程: 数据管理 → 超参数优化 → 模型训练 → 实验对比** — industrial_rac_hpo_main_docs_images_phase3_data, industrial_rac_hpo_main_docs_images_phase3_optimization, industrial_rac_hpo_main_docs_images_phase3_training, industrial_rac_hpo_main_docs_images_phase3_comparison [INFERRED 0.85]
- **优化监控面板组: 优化历史 + 目标分布 + 超参散点 + 任务状态** — industrial_rac_hpo_main_docs_images_phase3_optimization_optimization_history_chart, industrial_rac_hpo_main_docs_images_phase3_optimization_objective_distribution_histogram, industrial_rac_hpo_main_docs_images_phase3_panels_hyperparameter_objective_scatter, industrial_rac_hpo_main_docs_images_phase3_panels_task_status_progress [EXTRACTED 1.00]
- **算法基准对比组: rac_hpo / tpe_robust / tpe 在同一数据集上的 MAE 对比** — industrial_rac_hpo_main_docs_images_phase3_comparison_rac_hpo_algorithm, industrial_rac_hpo_main_docs_images_phase3_comparison_tpe_robust_algorithm, industrial_rac_hpo_main_docs_images_phase3_comparison_tpe_algorithm, industrial_rac_hpo_main_docs_images_phase3_comparison_validation_mae [EXTRACTED 1.00]
- **Sidebar Hover Expand/Collapse State Triptych** — industrial_rac_hpo_main_docs_images_sidebar_collapsed, industrial_rac_hpo_main_docs_images_sidebar_mid_animation, industrial_rac_hpo_main_docs_images_sidebar_expanded [EXTRACTED 1.00]
- **Collapsing Sidebar Design Constraints (overlay layout, stable icon anchor, active pill)** — industrial_rac_hpo_main_docs_images_sidebar_expanded_overlay_layout_no_reflow, industrial_rac_hpo_main_docs_images_sidebar_mid_animation_icon_anchor_stability, industrial_rac_hpo_main_docs_images_sidebar_collapsed_selected_pill_state [INFERRED 0.75]
- **Data Ingestion & Validation Flow (source CSV → uci_steel_energy_851 → stat cards → fixed split)** — industrial_rac_hpo_main_docs_images_step1_data_import_validation_panel, industrial_rac_hpo_main_docs_images_step1_data_csv_source_path, industrial_rac_hpo_main_docs_images_step1_data_uci_steel_energy_851, industrial_rac_hpo_main_docs_images_step1_data_dataset_stat_cards, industrial_rac_hpo_main_docs_images_step1_data_fixed_split_protocol [EXTRACTED 1.00]
- **Baseline LightGBM Training Flow (config → start training → metric cards → true validation results)** — industrial_rac_hpo_main_docs_images_step2_train_lightgbm_regressor_config, industrial_rac_hpo_main_docs_images_step2_train_start_baseline_button, industrial_rac_hpo_main_docs_images_step2_train_metric_cards, industrial_rac_hpo_main_docs_images_step2_train_true_validation_panel, industrial_rac_hpo_main_docs_images_step2_train_experiment_expb3cebfd309bb435b [EXTRACTED 1.00]
- **Data → Train → Hyperparameter Optimization Wizard Chain** — industrial_rac_hpo_main_docs_images_step1_data, industrial_rac_hpo_main_docs_images_step1_data_uci_steel_energy_851, industrial_rac_hpo_main_docs_images_step2_train, industrial_rac_hpo_main_docs_images_step2_train_validation_mae_metric, industrial_rac_hpo_main_docs_images_step2_train_hyperparameter_search_page [INFERRED 0.85]
- **Step 3 超参数搜索循证链：配置 → 结果卡片 → 平行坐标 / 优化历史 / 分布 / 试验表** — industrial_rac_hpo_main_docs_images_step3_optimize_hyperparameter_optimization_page, industrial_rac_hpo_main_docs_images_step3_optimize_result_summary_cards, industrial_rac_hpo_main_docs_images_step3_analysis_parallel_coordinates, industrial_rac_hpo_main_docs_images_step3_charts_optimization_history_chart, industrial_rac_hpo_main_docs_images_step3_charts_objective_distribution_histogram, industrial_rac_hpo_main_docs_images_step3_analysis_trials_table [EXTRACTED 1.00]
- **Step 4 实验对比流程：实验列表 → 单条观察卡片 → 勾选 → 并排查看表** — industrial_rac_hpo_main_docs_images_step4_compare_experiment_comparison_page, industrial_rac_hpo_main_docs_images_step4_compare_runs_list, industrial_rac_hpo_main_docs_images_step4_compare_current_run_cards, industrial_rac_hpo_main_docs_images_step4_compare_selected_selected_runs, industrial_rac_hpo_main_docs_images_step4_compare_selected_side_by_side_table [EXTRACTED 1.00]
- **公平 HPO 对照协议：同预算 48 次 + 同数据集 + MAE/J 双口径** — industrial_rac_hpo_main_docs_images_step3_optimize_rac_hpo_algorithm, industrial_rac_hpo_main_docs_images_step3_optimize_optuna_tpe_algorithm, industrial_rac_hpo_main_docs_images_step3_optimize_search_budget_48, industrial_rac_hpo_main_docs_images_step3_optimize_mae_metric, industrial_rac_hpo_main_docs_images_step3_charts_fixed_j_metric, industrial_rac_hpo_main_docs_images_step4_compare_uci_steel_energy_851_dataset [INFERRED 0.85]

## Communities (87 total, 23 thin omitted)

### Community 0 - "GUI 优化页集成测试"
Cohesion: 0.05
Nodes (39): OptimizePage, build_sidebar_navigation(), experiment(), page(), qt_app(), test_active_snapshot_does_not_replace_viewed_history(), test_active_timer_is_not_replaced_by_initial_snapshot_duration(), test_all_failed_search_never_displays_baseline_as_best() (+31 more)

### Community 1 - "代理模型与指标单元测试"
Cohesion: 0.06
Nodes (37): LoopPolicy, normalized_objective(), AppConfig, DataConfig, ExperimentConfig, load_config(), merge_config(), ModelConfig (+29 more)

### Community 2 - "工作区组件与集成测试"
Cohesion: 0.06
Nodes (12): _json(), _RecordModel, RecordTable, RunDetailDrawer, app(), test_clicking_selected_record_reopens_detail_once_per_click(), test_drawer_keeps_experiment_id_during_trial_drilldown_and_escape(), test_drawer_units_diagnostics_elapsed_labels_and_focus_are_truthful() (+4 more)

### Community 3 - "离线闭环服务与并发"
Cohesion: 0.09
Nodes (22): metrics(), predict(), LoopService, training_event(), TrainingBudgetExceeded, encode(), LoopRepository, run_loop_command() (+14 more)

### Community 4 - "RAC-HPO 架构设计文档"
Cohesion: 0.06
Nodes (52): cocoa 原生窗口七页可见性验证, LightGBM 的 libomp 23.1.5 Homebrew 原生依赖, macOS 运行与验证记录 (2026-11-09), QT_QPA_PLATFORM=offscreen 301 passed 回归, CLI 显式下载 Steel Energy 与 CNC Milling 公开数据, macOS 专用 PySide6-Essentials 6.9.3 依赖分支, ./Setup.command 依赖同步与导入检查, Random / TPE 共用的 ask/tell 搜索循环 (+44 more)

### Community 5 - "工业页 GUI 集成测试"
Cohesion: 0.06
Nodes (20): _finite(), IndustrialCurve, IndustrialPage, _json(), app(), display_fixture(), page(), test_industrial_classification_metrics_and_curve_keep_real_field_names() (+12 more)

### Community 6 - "工业基准服务与脚本"
Cohesion: 0.08
Nodes (23): campaign_row(), _descriptive_summary(), main(), _statistics(), summarize_campaign(), reject(), shared(), IndustrialService (+15 more)

### Community 7 - "Windows 启动回归测试"
Cohesion: 0.09
Nodes (14): main(), main(), configure_qt_platform(), main(), configure_qt_platform(), main(), download(), parser() (+6 more)

### Community 8 - "Agent 协作约定"
Cohesion: 0.05
Nodes (34): AGENTS：RAC-HPO 工程规则, CNC 按整把物理刀具划分并排除未来寿命标签, ARCHITECTURE：技术规范与实施架构, CNC Milling 2025 数据适配器（data/cnc_milling.py）, 质量/分布漂移监测与工程门禁（monitoring/drift）, 固定鲁棒目标 J（normalized_objective）, lifecycle.sqlite3 生命周期存储（infrastructure/loop_repository）, 受控单轮离线优化闭环（application/loop_service） (+26 more)

### Community 9 - "CNC 流水线集成测试"
Cohesion: 0.13
Nodes (18): main(), ApplicationService, emit(), progress(), save_trial(), utc_now(), write_json(), main() (+10 more)

### Community 10 - "数据审计与切分校验"
Cohesion: 0.09
Nodes (14): grouped_splits(), audit_features(), split_calendar_days(), validate_steel_frame(), evaluate(), group_evidence(), analyze_batch(), gate_metrics() (+6 more)

### Community 11 - "GUI 图表与工作区状态"
Cohesion: 0.13
Nodes (10): ParallelCoordinates, trial_color(), completed_trials(), filtered_trial_ids(), finite_value(), objective_label(), objective_value(), search_trials() (+2 more)

### Community 12 - "GUI 页面骨架"
Cohesion: 0.17
Nodes (10): card(), page_layout(), secondary(), table(), CollapsiblePanel, MetricCard, MetricsGrid, PanelGrid (+2 more)

### Community 13 - "GUI 主题与主窗口"
Cohesion: 0.14
Nodes (4): industrial_icon(), reduced_motion_enabled(), chevron_icon(), navigation_icon()

### Community 14 - "弱项复现与配置持久化"
Cohesion: 0.14
Nodes (6): repair_editable_path(), main(), main(), process_alive(), test_atomic_write_never_leaves_temporary_files(), test_unknown_schema_is_blocked_without_mutation()

### Community 15 - "数据加载与清单校验"
Cohesion: 0.12
Nodes (18): main(), download_steel(), prepare_steel_dataset(), steel_frame(), test_calendar_adapter_has_disjoint_date_splits_and_reproducible_manifest(), test_download_failure_cannot_create_success_file(), test_download_rejects_changed_official_csv(), test_download_validates_checksum_and_preserves_existing_files() (+10 more)

### Community 16 - "数据页与辅助工作区"
Cohesion: 0.13
Nodes (10): DataPage, TrainPage, fill_table(), format_value(), app(), test_collapsed_training_configuration_keeps_cancel_and_error_visible(), test_data_field_units_and_time_range_come_from_manifest(), test_data_missing_counts_remain_unknown() (+2 more)

### Community 17 - "Phase 3 界面截图"
Cohesion: 0.11
Nodes (29): 实验对比页面 (Experiment Comparison Page), 实验历史表格 (Experiment History Table), rac_hpo 算法 (RAC-HPO Search Algorithm), tpe 算法 (Plain TPE Baseline), tpe_robust 算法 (Robust TPE Baseline), 验证 MAE 指标 (Validation MAE, cycles), 数据管理页面 (Data Management Page), 预先定义的工况 ADOC_5mm / ADOC_10mm (+21 more)

### Community 18 - "鲁棒目标与分类阈值"
Cohesion: 0.12
Nodes (15): robust_metrics(), apply_robust_metrics(), temporal_fixture(), test_threshold_folds_are_chronological_and_keep_equal_times_together(), test_time_oof_rejects_group_overlap_with_outer_validation(), test_time_oof_rejects_other_physical_groups_crossing_a_fold(), test_time_oof_rejects_unknown_time_physical_groups_and_multiclass(), test_trained_threshold_and_model_never_depend_on_validation_labels() (+7 more)

### Community 19 - "分类优化流程"
Cohesion: 0.13
Nodes (16): optimize(), _policy_history(), _public_diagnostics(), _score(), train(), validate_parameters(), fixture_dataset(), test_cancellation_after_baseline_retains_completed_baseline() (+8 more)

### Community 20 - "training lightgbm trainer"
Cohesion: 0.11
Nodes (13): OptimizationResult, TrainingResult, _suggest(), validate_search_space(), grid_candidates(), resource_pruner(), build_regressor(), train() (+5 more)

### Community 21 - "test environment snapshot"
Cohesion: 0.13
Nodes (8): environment_snapshot(), file_hash(), save_convergence(), source_fingerprint(), write_yaml(), test_snapshot_accepts_pyside6_essentials(), test_snapshot_records_commit_when_git_succeeds(), test_snapshot_survives_missing_git_executable()

### Community 22 - "test optimization test"
Cohesion: 0.17
Nodes (19): optimize(), config(), metric_result(), small_dataset(), test_budget_exhausted_before_first_trial_cannot_report_completion(), test_budget_is_checked_before_next_trial_and_overrun_is_explicit(), runner(), test_cancellation_is_acknowledged_and_does_not_look_completed() (+11 more)

### Community 23 - "step3 optimize search"
Cohesion: 0.13
Nodes (24): 超参数重要性面板（显示「尚未提供」）, 优化分析页（平行坐标 + 超参数重要性）, 平行坐标图：6 个参数轴，一条折线＝一次试验, Trials 搜索试验表（编号 / 状态 / 目标 MAE）, 固定 J 指标（配置固定时的目标值）, 超参数与目标关系散点图（feature_fraction vs 目标 MAE）, 各试验目标分布直方图（按 MAE 区间分桶）, 优化历史折线图（灰点＝本次目标，蓝线＝累计最优） (+16 more)

### Community 24 - "interfaces gui main"
Cohesion: 0.17
Nodes (3): stopped(), MainWindow, test_gui_cnc_chooser_runs_real_rac_and_displays_diagnostics()

### Community 25 - "test industrial data"
Cohesion: 0.13
Nodes (17): prepare(), ai4i_csv(), stored_rar(), test_ai4i_excludes_identity_and_all_failure_causes(), test_ai4i_ucimlrepo_unitless_feature_names_supported_without_mutating_source(), test_cached_archive_rejects_new_symlink(), test_dataset_fingerprint_does_not_depend_on_install_directory(), test_lenovo_authorization_required() (+9 more)

### Community 26 - "data cnc milling"
Cohesion: 0.15
Nodes (8): runner(), download_cnc_milling(), prepare_cnc_milling(), prepare(), PreparedDataset, test_cnc_rejects_invalid_schema(), test_real_cnc_has_physical_tool_holdouts_and_no_target_features(), dataset()

### Community 27 - "test summary alignment"
Cohesion: 0.12
Nodes (14): TaskCancelled, report(), runner(), test_training_cancels_from_iteration_callback(), result(), test_classification_reports_fault_misses_and_false_alarms(), test_grid_exhausts_without_duplicates_and_obeys_steps(), test_invalid_resource_controls_fail_before_training() (+6 more)

### Community 29 - "phase1 comparison"
Cohesion: 0.19
Nodes (20): Phase 1 实验对比页面截图, 实验历史表（实验 ID / 算法 / 状态 / 验证 MAE / 固定划分 / 耗时 / 试验数）, random 随机搜索算法（验证 MAE 13.5042，固定划分 0.85079，16 次试验）, 分工况指标（weekday MAE 15.3892, samples 4992；reliability descriptive_only）, Phase 1 数据管理页面截图, 固定时间划分（gap=192, test=7104, train=20832, validation=6912）, RAC-HPO 应用外壳（工业模型训练与超参数优化，v0.1.0，LightGBM · Optuna）, 数据集 uci_steel_energy_851（35,040 条记录，5 个特征，目标 Usage_kWh） (+12 more)

### Community 30 - "test workspace lifecycle"
Cohesion: 0.22
Nodes (12): test_loop_progress_and_terminal_do_not_replace_viewed_history(), snapshot(), test_delayed_render_does_not_restore_running_after_terminal_result(), test_duplicate_events_are_deduplicated_and_baseline_not_progress(), test_failed_import_does_not_relabel_previous_completed_experiment(), test_failed_result_received_via_finished_remains_visible(), test_history_does_not_change_new_run_inputs_and_live_events_do_not_mix(), test_live_snapshot_uses_recorded_baseline_time_and_best_trial_metrics() (+4 more)

### Community 32 - "data industrial common"
Cohesion: 0.28
Nodes (11): prepare_paderborn(), signal_features(), make_dataset(), sha256(), source_metadata(), unpack_cached_archive(), verify(), _prepare_documented_table() (+3 more)

### Community 33 - "test industrial benchmark"
Cohesion: 0.15
Nodes (7): campaign_fixture(), test_audit_failure_and_absent_runs_are_explicitly_noncomparable(), test_campaign_row_keeps_actual_controls_and_excludes_baseline_from_trial_budget(), test_complete_paired_campaign_is_fair_and_baseline_is_separate(), test_main_persists_verified_fair_summary_from_complete_service_records(), test_missing_changed_or_failed_evidence_never_generates_fair_means(), test_qt_platform_configuration()

### Community 34 - "step1 data"
Cohesion: 0.15
Nodes (17): Step 1: Data Management Screen (智训引擎 · LightGBM · 数据管理), 智训引擎 Desktop App Shell (工业模型训练与超参数优化, left icon rail + top experiment status bar), Source CSV Path datasets/raw/steel_energy/Steel_industry_data.csv, Dataset Summary Cards (记录数 35,040 · 特征数 5 · 目标 Usage_kWh · 单位 kWh), Experiment exp-4ddb69f85302415b (status: completed), 固定划分与先验概况 (Fixed Train/Val/Test Split, Frozen Test Set), 数据导入与校验 (Data Import & Validation) Panel, Dataset uci_steel_energy_851 (UCI 钢铁能耗·日历基线) (+9 more)

### Community 35 - "data loop views"
Cohesion: 0.32
Nodes (12): build_protocol(), build_view(), digest(), load_view(), replay_rows(), sample_metadata(), save_view(), simulate_features() (+4 more)

### Community 36 - "industrial ai4i 2020"
Cohesion: 0.15
Nodes (15): AI4I 2020 合成维护数据集, 工业实验与分类指标面板（balanced accuracy / Macro F1 / Log loss / 实验总耗时）, 实验级标签页（数据审计 / 各工况 / 搜索记录 / 搜索曲线 / 训练曲线 / 配置与模型产物 / 日志）, 工业训练 · 分类与多工况搜索页面, 新任务 数据与训练配置（随机森林 / 固定参数基线 / 固定种子）, 日志导出与清空显示控件（自动滚动 / 复制 / 导出日志 / 清空显示）, 运行日志 · 当前会话页面, 任务事件日志流（收到 114 事件 / 当前匹配 114 条） (+7 more)

### Community 37 - "data industrial uci"
Cohesion: 0.28
Nodes (10): _fetch_one_bearing(), fetch_paderborn(), _range(), chronological_splits(), utc_now(), write_json(), fetch(), fetch_uci() (+2 more)

### Community 38 - "interfaces gui pages"
Cohesion: 0.18
Nodes (5): ComparePage, ComparisonPanel, display_time(), test_history_numeric_sort_paging_filter_and_export_use_id(), test_sorted_history_keeps_selected_experiment_id()

### Community 40 - "interfaces gui pages"
Cohesion: 0.22
Nodes (3): LogsPage, test_logs_append_without_rewriting_existing_document(), test_logs_filter_export_clear_and_manual_scroll()

### Community 41 - "training classification estimator"
Cohesion: 0.19
Nodes (6): _estimator(), before_iteration(), _fit_forest(), _fold_probabilities(), _preprocessor(), acknowledge_cancel()

### Community 42 - "industrial algorithm optimization"
Cohesion: 0.21
Nodes (10): SECOM 半导体工艺数据集, ExtraTrees 分工况误差与成本代理, TPE 暖启动 / 全局探索 / 代理采集 / 回退决策流, 工业训练与 RAC-HPO 优化计划, 工业训练与 RAC-HPO 优化实验报告, 同一模型阈值配对消融（11/11 漏判 vs 训练侧阈值）, SECOM 类别失衡开发探针（0.04 阈值，召回 2/10）, SECOM 同预算三种子 Random/TPE/RAC 对照 (+2 more)

### Community 43 - "algorithm guide regime"
Cohesion: 0.21
Nodes (7): RAC-HPO 算法详解, 业务模型与搜索代理两层划分, 全局+局部候选池构造（128 个候选）, 分工况误差 E_g（MAE / 1-BA）, 授权训练预算（1 基线 + 至多一次 HPO，总 300 秒）, 答辩备忘录, MAE 与 J 的排序反转证据

### Community 44 - "controlled loop report"
Cohesion: 0.22
Nodes (9): 智训引擎：受控单轮离线闭环, 独立 lifecycle.sqlite3 生命周期库（Schema 1）, 人工本地切换与回滚, 智训引擎受控闭环交付报告, 闭环真实验收记录 LOOP-61baace896474f1b, 门禁拒绝案例（ADOC_10mm 22.08 vs 17.15）, 18 个受保护文件与原实验库一致性校验, 213 项完整回归（0 失败，157.972 秒） (+1 more)

### Community 45 - "infrastructure database experimentrepository"
Cohesion: 0.27
Nodes (4): encode(), ExperimentRepository, test_repository_connection_is_closed_after_context(), test_repository_retains_failed_trials_and_regimes()

### Community 46 - "evaluation classification rationale"
Cohesion: 0.20
Nodes (6): evaluate(), _metrics(), _scalar(), choose_time_oof_threshold(), _fingerprint(), test_evaluator_sparse_classes_and_independent_groups()

### Community 47 - "test gui test"
Cohesion: 0.21
Nodes (7): qt_app(), test_gui_cancellation_is_confirmed_by_real_worker(), test_gui_imports_real_dataset_in_background(), test_gui_real_baseline_search_and_export(), test_gui_reports_actual_backend_errors(), wait_for_idle(), window()

### Community 48 - "sidebar collapse ui"
Cohesion: 0.15
Nodes (11): CollapsingSidebar 折叠侧边栏（方案 B）, NavigationDelegate 图标与药丸绘制委托, 减少动画检测 reduced_motion_enabled（SPI_GETCLIENTAREAANIMATION）, tests/integration/test_sidebar.py 11 项行为测试, 导航色 token（nav_text / nav_selected_bg / nav_selected）, quality_audit.json 工业数据异常审计（1.5 IQR）, 总结与展望对齐记录（2026-11-04）, RAC-HPO 实验工作区 UI 重构报告 (+3 more)

### Community 49 - "data industrial common"
Cohesion: 0.21
Nodes (4): unpack_rar4(), unpack_archive(), test_archive_existing_file_preserved(), test_archive_traversal_rejected_before_extraction()

### Community 50 - "configs default data"
Cohesion: 0.18
Nodes (10): data, dataset_id, path, experiment, name, seed, output, save_model (+2 more)

### Community 51 - "summary alignment benchmark"
Cohesion: 0.22
Nodes (10): M5 本机七方法同预算验收表, Grid 三档粗网格（默认 3^6=729 点）, Setup.command / Run-GUI.command 本机脚本, RAC 代理门禁与回退机制, Successive Halving / Hyperband 资源剪枝对照, cnc_milling_2025 CNC 刀具剩余周期数据集（CycleToFailure）, 自主优化单轮离线闭环（授权/回放/门禁/人工切换）, finalize 最终评估（train+validation 重训后读 test） (+2 more)

### Community 54 - "configs default feature"
Cohesion: 0.22
Nodes (9): high, low, type, high, low, type, search_space, feature_fraction (+1 more)

### Community 55 - "datasets industrial sources"
Cohesion: 0.28
Nodes (6): 工业数据来源与接入审计, 联想智能工厂授权本地导入契约, Paderborn 轴承数据中心数据集, Pneumatic Pressure 离散制造现场数据集, XJTU-SY 轴承加速寿命数据集, Paderborn 小子集结果（Random J 0.6792 优于 RAC 0.6930）

### Community 56 - "ui workbench v2"
Cohesion: 0.25
Nodes (6): 结构化试验详情/对比抽屉（Esc 与焦点恢复）, 优化页六指标四个真实图表面板, TopBar / 全局任务栏 / WorkspaceHeader 工作区外壳, 参数平行坐标与范围刷选联动, 七页工作台（数据/训练/优化/对比/日志/自主优化/工业训练）, 智训引擎用户手册

### Community 58 - "industrial training report"
Cohesion: 0.32
Nodes (6): AI4I 2020 预测性维护数据集（合成数据）, 工业数据接入与分类训练实施计划, 工业侧模块布局（data/training/evaluation/optimization/application）, 工业数据接入与分类训练报告, AI4I 合成基准结果（BA 0.7476，J 0.9908）, 45 个模型哈希/重载/同配置重训一致性校验

### Community 59 - "sidebar mid animation"
Cohesion: 0.43
Nodes (8): Sidebar Collapsed State Screenshot (60px icon rail), Selected Navigation Pill State (light blue rounded highlight on active page), Sidebar Expanded State Screenshot (200px with labels), Five-Page Workbench Navigation (Data / Training / HPO / Experiments / Logs), Overlay Layout: Expanded Sidebar Covers Content Without Reflowing It, Sidebar Mid-Animation Screenshot (partial fade + width interpolation), Collapsing Sidebar Navigation Pattern (auto-expand on hover, overlay instead of push), Icon Anchor Stability During Width Animation (icons keep fixed x, only labels fade/shift)

### Community 62 - "datasets sources"
Cohesion: 0.33
Nodes (6): 数据来源与使用范围（钢铁/CNC/NASA Milling）, CNC Milling Process Dataset 2025, scripts/download_steel.py 下载校验脚本, NASA Milling 铣削磨损数据集, UCI Steel Industry Energy Consumption 数据集, 20 行一批的整刀回放与标签释放

### Community 64 - "configs default lambda"
Cohesion: 0.40
Nodes (5): high, log, low, type, lambda_l2

### Community 65 - "configs default learning"
Cohesion: 0.40
Nodes (5): high, log, low, type, learning_rate

### Community 66 - "configs default model"
Cohesion: 0.40
Nodes (5): model, early_stopping_rounds, n_estimators, n_jobs, name

### Community 67 - "test workbench v2"
Cohesion: 0.40
Nodes (3): apply_theme(), app(), window()

### Community 69 - "configs default min"
Cohesion: 0.50
Nodes (4): high, low, type, min_child_samples

### Community 70 - "configs default num"
Cohesion: 0.50
Nodes (4): high, low, type, num_leaves

### Community 71 - "configs default optimization"
Cohesion: 0.50
Nodes (4): optimization, algorithm, max_trials, timeout_seconds

### Community 72 - "configs default robustness"
Cohesion: 0.50
Nodes (4): robustness, alpha, epsilon, minimum_independent_groups

### Community 74 - "ui design no"
Cohesion: 0.50
Nodes (3): 平行坐标与参数 brush 交互, Trial 稳定 ID（experiment_id:number，基线 -1 排除）, WorkspaceViewState 纯展示状态

## Knowledge Gaps
- **53 isolated node(s):** `industrial-rac-hpo`, `代理前向质量门槛（ExtraTrees 前向检验）`, `代理不合格时显式回退 TPE`, `lifecycle.sqlite3 生命周期存储（infrastructure/loop_repository）`, `质量/分布漂移监测与工程门禁（monitoring/drift）` (+48 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 423 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **23 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `MainWindow` connect `interfaces gui main` to `GUI 优化页集成测试`, `离线闭环服务与并发`, `test workbench v2`, `工业页 GUI 集成测试`, `工业基准服务与脚本`, `Windows 启动回归测试`, `interfaces gui pages`, `CNC 流水线集成测试`, `interfaces gui pages`, `interfaces gui sidebar`, `GUI 主题与主窗口`, `test gui test`, `数据页与辅助工作区`, `interfaces gui workers`, `interfaces gui workspace`, `interfaces gui widgets`, `test workspace lifecycle`, `interfaces gui pages`?**
  _High betweenness centrality (0.036) - this node is a cross-community bridge._
- **Are the 22 inferred relationships involving `OptimizePage` (e.g. with `MainWindow` and `ExperimentChart`) actually correct?**
  _`OptimizePage` has 22 INFERRED edges - model-reasoned connections that need verification._
- **What connects `industrial-rac-hpo`, `代理前向质量门槛（ExtraTrees 前向检验）`, `代理不合格时显式回退 TPE` to the rest of the system?**
  _53 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `GUI 优化页集成测试` be split into smaller, more focused modules?**
  _Cohesion score 0.053998632946001365 - nodes in this community are weakly interconnected._
- **Why does `OptimizePage` connect `GUI 优化页集成测试` to `工作区组件与集成测试`, `interfaces gui pages`, `interfaces gui pages`, `interfaces gui workspace`, `GUI 图表与工作区状态`, `GUI 页面骨架`, `GUI 主题与主窗口`, `interfaces gui workbench`, `数据页与辅助工作区`, `interfaces gui main`, `interfaces gui charts`, `interfaces gui pages`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **Are the 24 inferred relationships involving `MainWindow` (e.g. with `main()` and `main()`) actually correct?**
  _`MainWindow` has 24 INFERRED edges - model-reasoned connections that need verification._
- **Should `代理模型与指标单元测试` be split into smaller, more focused modules?**
  _Cohesion score 0.058018018018018015 - nodes in this community are weakly interconnected._