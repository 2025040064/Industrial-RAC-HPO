"""Classification workspace. Rendering never trains or manufactures measurements."""

import json
import math

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QTabWidget,
    QVBoxLayout, QWidget,
)

from ..widgets import card, fill_table, secondary, table
from ..workspace_widgets import MetricsGrid, PanelGrid, WorkspaceHeader


DATASETS = (
    ('AI4I 2020 · 合成维护数据', 'ai4i_2020'), ('SECOM · 半导体制造', 'secom'),
    ('Paderborn · 轴承多工况', 'paderborn'), ('XJTU-SY · 轴承寿命', 'xjtu_sy'),
    ('联想智能工厂 · 需授权', 'lenovo'), ('Pneumatic Pressure · 气压', 'pneumatic_pressure'),
)


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _finite(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


class IndustrialCurve(QWidget):
    """Only saved validation errors are plotted; regression charts stay separate."""

    def __init__(self, parent=None, *, kind='search'):
        super().__init__(parent)
        self.kind = kind
        self.points = []
        self.train_points = []
        self.empty_reason = ''
        self.setMinimumHeight(220)
        self.setAccessibleName('真实模型迭代损失曲线' if kind == 'training' else '真实分类验证错误与累计最优搜索曲线')

    def set_trials(self, trials):
        self.points = []
        for trial in trials:
            number = trial.get('number', -1)
            if number < 0 or trial.get('status') not in ('completed', 'COMPLETE', None):
                continue
            metrics = trial.get('metrics') or {}
            score = metrics.get('overall_balanced_accuracy', metrics.get('balanced_accuracy'))
            if _finite(score):
                self.points.append((number, 1 - score))
        self.points.sort()
        self.update()

    def set_learning_curve(self, metrics):
        curve = metrics.get('learning_curve') or []
        self.points = [(record['iteration'], record['validation_loss']) for record in curve
                       if _finite(record.get('iteration')) and _finite(record.get('validation_loss'))]
        self.train_points = [(record['iteration'], record['train_loss']) for record in curve
                             if _finite(record.get('iteration')) and _finite(record.get('train_loss'))]
        self.empty_reason = str(metrics.get('learning_curve_reason') or '此模型没有已保存的逐迭代训练曲线')
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor('#64748b'))
        if not self.points:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             self.empty_reason if self.kind == 'training' else '暂无真实搜索曲线\n基线不计入搜索')
            return
        rect = self.rect().adjusted(65, 38, -22, -46)
        painter.drawText(12, 22, '模型迭代损失（越低越好）' if self.kind == 'training' else '验证错误 = 1 − balanced accuracy（越低越好）')
        painter.drawText(rect.left(), self.height() - 12,
                         '迭代轮次；蓝色验证，橙色训练' if self.kind == 'training' else '已完成 Trial；橙色为累计最优')
        painter.setPen(QPen(QColor('#cbd5e1'), 1))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.drawLine(rect.topLeft(), rect.bottomLeft())
        all_points = self.points + self.train_points
        low = min(value for _, value in all_points)
        high = max(value for _, value in all_points)
        margin = max((high - low) * .1, .01)
        low, high = max(0, low - margin), high + margin
        if high <= low:
            high = low + .01
        first, last = self.points[0][0], max(self.points[-1][0], self.points[0][0] + 1)
        def point(number, value):
            return QPointF(rect.left() + (number - first) / (last - first) * rect.width(),
                           rect.bottom() - (value - low) / (high - low) * rect.height())
        previous = previous_best = None
        best = math.inf
        train_values = dict(self.train_points)
        for number, value in self.points:
            current = point(number, value)
            best = min(best, value)
            second_value = train_values.get(number) if self.kind == 'training' else best
            current_best = point(number, second_value) if second_value is not None else None
            painter.setPen(QPen(QColor('#2563eb'), 2))
            if previous is not None:
                painter.drawLine(previous, current)
            painter.drawEllipse(current, 3, 3)
            painter.setPen(QPen(QColor('#d97706'), 2))
            if previous_best is not None and current_best is not None:
                painter.drawLine(previous_best, current_best)
            previous, previous_best = current, current_best
        painter.setPen(QColor('#64748b'))
        painter.drawText(6, rect.top() + 8, f'{high:.3f}')
        painter.drawText(6, rect.bottom(), f'{low:.3f}')
        painter.drawText(rect.left(), rect.bottom() + 18, str(self.points[0][0]))
        painter.drawText(rect.right() - 30, rect.bottom() + 18, str(self.points[-1][0]))


class IndustrialPage(QWidget):
    operation_requested = Signal(str, dict)
    cancel_requested = Signal()
    refresh_requested = Signal()
    run_selected = Signal(str)
    compare_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.snapshot = {}
        self.busy = False
        self.active_run_id = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        layout.addWidget(WorkspaceHeader('工业训练 · 分类与多工况搜索',
            '先核验来源与划分，再运行真实训练。AI4I 为合成数据；测试集封存，分类指标单独展示。'))
        self.status_label = QLabel('尚无工业训练记录。选择数据源后显式获取，或导入本地文件并审计。')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        panels = PanelGrid()
        layout.addWidget(panels)
        setup, setup_layout = card('新任务 · 数据与训练配置')
        self.dataset_combo = QComboBox()
        for label, key in DATASETS:
            self.dataset_combo.addItem(label, key)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText('留空使用已获取文件；本地归档或解压目录可在此指定')
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        browse_button = QPushButton('选择文件')
        browse_button.clicked.connect(self._browse)
        folder_button = QPushButton('选择目录')
        folder_button.clicked.connect(self._browse_folder)
        path_row.addWidget(browse_button)
        path_row.addWidget(folder_button)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow('数据源', self.dataset_combo)
        setup_layout.addLayout(form)
        setup_layout.addLayout(path_row)
        source_actions = QHBoxLayout()
        self.fetch_button = QPushButton('显式获取公开数据')
        self.audit_button = QPushButton('审计本地数据')
        self.fetch_button.clicked.connect(lambda: self._request('fetch'))
        self.audit_button.clicked.connect(lambda: self._request('audit'))
        source_actions.addWidget(self.fetch_button)
        source_actions.addWidget(self.audit_button)
        setup_layout.addLayout(source_actions)
        self.source_note = secondary('')
        setup_layout.addWidget(self.source_note)
        self.dataset_combo.currentIndexChanged.connect(self._dataset_changed)
        self.model_combo = QComboBox()
        for label, key in [('Random Forest', 'random_forest'), ('XGBoost', 'xgboost'), ('LightGBM', 'lightgbm')]:
            self.model_combo.addItem(label, key)
        self.algorithm_combo = QComboBox()
        for label, key in [('固定参数基线', 'baseline'), ('Random Search', 'random'),
                           ('Optuna TPE', 'tpe'), ('多工况自适应 RAC-HPO', 'rac_hpo')]:
            self.algorithm_combo.addItem(label, key)
        self.decision_combo = QComboBox()
        for label, key in [('默认决策阈值', 'native'), ('训练期时序阈值', 'time_oof')]:
            self.decision_combo.addItem(label, key)
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 2147483647)
        self.seed_spin.setValue(42)
        self.trials_spin = QSpinBox()
        self.trials_spin.setRange(1, 10000)
        self.trials_spin.setValue(24)
        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(.1, 86400)
        self.timeout_spin.setValue(300)
        self.timeout_spin.setSuffix(' s')
        train_form = QFormLayout()
        train_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        for label, widget in [('模型', self.model_combo), ('方法', self.algorithm_combo), ('决策策略', self.decision_combo),
                              ('随机种子', self.seed_spin), ('搜索试验上限', self.trials_spin),
                              ('墙钟预算', self.timeout_spin)]:
            train_form.addRow(label, widget)
        setup_layout.addLayout(train_form)
        setup_layout.addWidget(secondary('固定划分与资源由服务保存。每个来源独立训练；未支持的任务或缺失依赖将明确失败。'))
        setup_layout.addWidget(secondary('时序阈值仅用于有可靠时间顺序的二分类；轴承分组任务不支持，且需要额外训练时间。'))
        run_actions = QHBoxLayout()
        self.start_button = QPushButton('开始真实训练')
        self.start_button.setObjectName('primary')
        self.cancel_button = QPushButton('取消训练')
        self.start_button.clicked.connect(lambda: self._request('run'))
        self.cancel_button.clicked.connect(self.cancel_requested)
        run_actions.addWidget(self.start_button)
        run_actions.addWidget(self.cancel_button)
        setup_layout.addLayout(run_actions)
        panels.add_panel(setup)
        result, result_layout = card('工业实验与分类指标')
        history_row = QHBoxLayout()
        self.history_combo = QComboBox()
        self.history_combo.setPlaceholderText('尚无工业训练记录')
        self.history_combo.setMinimumWidth(0)
        self.history_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.history_combo.activated.connect(lambda index: self.run_selected.emit(self.history_combo.itemData(index)))
        refresh = QPushButton('刷新')
        refresh.clicked.connect(self.refresh_requested)
        history_row.addWidget(self.history_combo, 1)
        history_row.addWidget(refresh)
        result_layout.addLayout(history_row)
        self.metrics = MetricsGrid([('balanced_accuracy', '验证 balanced accuracy'), ('f1_macro', '验证 Macro F1'),
                                    ('log_loss', '验证 Log loss'), ('duration', '实验总耗时 / s')])
        result_layout.addWidget(self.metrics)
        self.failure_label = QLabel('')
        self.failure_label.setObjectName('error')
        self.failure_label.setWordWrap(True)
        result_layout.addWidget(self.failure_label)
        self.weak_regime_label = secondary('尚无已保存的验证工况指标。')
        result_layout.addWidget(self.weak_regime_label)
        self.tabs = QTabWidget()
        self.audit_view = QPlainTextEdit()
        self.audit_view.setReadOnly(True)
        self.audit_view.setPlaceholderText('审计记录包括真实来源、许可、文件哈希、获取日期、标签与固定划分。')
        self.regime_table = table(['验证工况', '样本数', '平衡准确率', 'Macro F1', 'Log loss'])
        self.trial_table = table(['Trial', '状态', '目标值', '平衡准确率', '耗时 / s', '超参数'])
        self.curve = IndustrialCurve()
        self.learning_curve = IndustrialCurve(kind='training')
        self.details_view = QPlainTextEdit()
        self.details_view.setReadOnly(True)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(3000)
        for widget, title in [(self.audit_view, '数据审计'), (self.regime_table, '各工况'),
                              (self.trial_table, '搜索记录'), (self.curve, '搜索曲线'), (self.learning_curve, '训练曲线'),
                              (self.details_view, '配置与模型产物'), (self.log_view, '日志')]:
            self.tabs.addTab(widget, title)
        result_layout.addWidget(self.tabs)
        panels.add_panel(result)
        compare, compare_layout = card('模型与方法对比 · 仅查看真实验证结果')
        compare_row = QHBoxLayout()
        self.compare_combo = QComboBox()
        self.compare_combo.setPlaceholderText('选择另一条工业实验')
        self.compare_combo.setMinimumWidth(0)
        self.compare_button = QPushButton('与当前实验并排查看')
        self.compare_button.clicked.connect(self._compare)
        compare_row.addWidget(self.compare_combo, 1)
        compare_row.addWidget(self.compare_button)
        compare_layout.addLayout(compare_row)
        self.compare_note = secondary('只有任务、数据版本、划分、模型和搜索预算一致的实验才能形成方法对照；这里不生成跨任务排名。')
        compare_layout.addWidget(self.compare_note)
        self.compare_table = table(['记录项', '当前实验', '对比实验'])
        compare_layout.addWidget(self.compare_table)
        layout.addWidget(compare)
        layout.addStretch()
        self._dataset_changed()
        self.set_busy(False)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择本地数据文件或归档', self.path_edit.text())
        if path:
            self.path_edit.setText(path)

    def _browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, '选择本地数据目录', self.path_edit.text())
        if path:
            self.path_edit.setText(path)

    def _dataset_changed(self):
        key = self.dataset_combo.currentData()
        notes = {
            'ai4i_2020': 'AI4I 是 UCI 明确标注的合成数据，仅作为维护分类基准，不代表真实工厂生产记录。',
            'secom': 'SECOM 为半导体制造测量；按时间顺序验证，缺失填补仅拟合训练集。',
            'paderborn': 'Paderborn 使用本地归档或目录。先验证小样本，按物理轴承分组并分别记录工况。',
            'xjtu_sy': 'XJTU-SY 使用本地归档或目录。寿命预测任务需要独立时序训练器；不将其混入分类比较。',
            'lenovo': '联想数据需要申请和授权。只导入已获授权的本地文件，不绕过下载权限。',
            'pneumatic_pressure': '先审计公开来源与实际标签；任务与模型适配通过后才训练。',
        }
        self.source_note.setText(notes[key])

    def _request(self, operation):
        arguments = {'dataset_key': self.dataset_combo.currentData()}
        path = self.path_edit.text().strip() or None
        if operation == 'audit':
            arguments['path'] = path
        elif operation == 'run':
            arguments.update(model_name=self.model_combo.currentData(), algorithm=self.algorithm_combo.currentData(),
                             data_path=path, seed=self.seed_spin.value(), max_trials=self.trials_spin.value(),
                             timeout_seconds=self.timeout_spin.value())
            if self.decision_combo.currentData() != 'native':
                arguments['model_config'] = {'decision_mode': self.decision_combo.currentData()}
            self.active_run_id = None
            self.snapshot = {}
            self.failure_label.clear()
            self.curve.set_trials([])
            self.trial_table.setRowCount(0)
            self.status_label.setText('正在启动新的真实工业训练…')
        self.operation_requested.emit(operation, arguments)

    def set_busy(self, busy, cancellable=False):
        self.busy = busy
        for widget in (self.start_button, self.audit_button, self.fetch_button, self.dataset_combo,
                       self.path_edit, self.model_combo, self.algorithm_combo, self.decision_combo, self.seed_spin,
                       self.trials_spin, self.timeout_spin):
            widget.setEnabled(not busy)
        self.cancel_button.setEnabled(cancellable)

    def show_audit(self, result):
        self.failure_label.clear()
        self.audit_view.setPlainText(_json(result))
        self.tabs.setCurrentWidget(self.audit_view)
        self.status_label.setText('数据操作已保存。审计与来源记录见下方；训练不会隐式下载。')

    def set_history(self, records):
        current = self.snapshot.get('id')
        compare = self.compare_combo.currentData()
        for combo in (self.history_combo, self.compare_combo):
            combo.clear()
            for record in records:
                combo.addItem(f"{record.get('dataset_key', '')} · {record.get('model_name', '')} · "
                              f"{record.get('algorithm', '')} · {record.get('status', '')} · {record['id']}", record['id'])
        if current:
            self.history_combo.setCurrentIndex(self.history_combo.findData(current))
        if compare:
            self.compare_combo.setCurrentIndex(self.compare_combo.findData(compare))

    def show_result(self, result):
        previous_id = self.snapshot.get('id')
        self.snapshot = result
        identifier = result.get('id')
        self.status_label.setText(f"{identifier or '—'} · {result.get('dataset_key', '')} · "
                                  f"{result.get('model_name', '')} · {result.get('status', 'running')}")
        metrics = result.get('metrics') or {}
        for key in ('balanced_accuracy', 'f1_macro', 'log_loss'):
            self.metrics.set_metric(key, metrics.get('overall_' + key, metrics.get(key)))
        self.metrics.set_metric('duration', result.get('duration_seconds'))
        regimes = metrics.get('regime_metrics', metrics.get('per_regime', metrics.get('regimes', {})))
        if isinstance(regimes, list):
            regimes = {item.get('regime', item.get('name', str(index))): item for index, item in enumerate(regimes)}
        valid_regimes = [(name, values) for name, values in regimes.items()
                         if isinstance(values, dict) and _finite(values.get('balanced_accuracy'))]
        if valid_regimes:
            name, values = min(valid_regimes, key=lambda item: item[1]['balanced_accuracy'])
            groups = values.get('effective_independent_groups', values.get('independent_groups'))
            warning = '少数类样本不足，仅作描述。' if values.get('sparse_class_warning') else '仅描述本次验证结果。'
            self.weak_regime_label.setText(f"薄弱验证工况：{name}；balanced accuracy={values['balanced_accuracy']:.6g}；"
                f"样本={values.get('samples', '—')}，少数类={values.get('minority_class_samples', '—')}，"
                f"独立组={groups if groups is not None else '—'}。{warning}")
        else:
            self.weak_regime_label.setText('尚无已保存的验证工况指标。')
        fill_table(self.regime_table, [[name, values.get('samples', values.get('n_samples', values.get('sample_count', values.get('count')))),
                    values.get('balanced_accuracy'), values.get('f1_macro'), values.get('log_loss')]
                    for name, values in regimes.items() if isinstance(values, dict)])
        trials = result.get('trials') or []
        fill_table(self.trial_table, [[trial.get('number'), trial.get('status'), trial.get('objective'),
            (trial.get('metrics') or {}).get('overall_balanced_accuracy'), trial.get('duration_seconds'),
            _json(trial.get('params', {}))] for trial in trials])
        self.curve.set_trials(trials)
        self.learning_curve.set_learning_curve(metrics)
        self.audit_view.setPlainText(_json(result.get('manifest', {})))
        self.details_view.setPlainText(_json({key: result.get(key) for key in (
            'task_type', 'best_params', 'best_trial', 'best_value', 'config', 'artifacts', 'failure_reason')}))
        classification_metrics = {key: metrics[key] for key in (
            'overall_average_precision', 'decision_policy', 'regimes') if key in metrics}
        if classification_metrics:
            self.details_view.appendPlainText('\n' + _json({'classification_metrics': classification_metrics}))
        self.failure_label.setText(str(result.get('failure_reason') or ''))
        if result.get('log_text') is not None:
            self.log_view.setPlainText(str(result['log_text']))
        elif previous_id != identifier:
            self.log_view.clear()
        self.history_combo.setCurrentIndex(self.history_combo.findData(identifier))

    def append_progress(self, event):
        self.log_view.appendPlainText(_json(event))
        identifier = event.get('run_id')
        if event.get('type') == 'started':
            self.active_run_id = identifier
        if identifier and self.snapshot.get('id') not in (None, identifier):
            return
        trial = event.get('trial')
        if isinstance(trial, dict):
            snapshot = dict(self.snapshot)
            snapshot.pop('log_text', None)
            records = {item['number']: item for item in snapshot.get('trials', [])}
            records[trial['number']] = trial
            snapshot.update(id=identifier, status='running', trials=sorted(records.values(), key=lambda item: item['number']))
            self.show_result(snapshot)

    def show_error(self, message, trace=''):
        self.failure_label.setText(str(message))
        self.status_label.setText('工业数据操作或训练失败，原因与日志已保留。')
        self.log_view.appendPlainText(f'industrial_operation_failed error={message}\n{trace}')
        self.tabs.setCurrentWidget(self.log_view)

    def _compare(self):
        if self.snapshot.get('id') and self.compare_combo.currentData():
            self.compare_requested.emit(self.snapshot['id'], self.compare_combo.currentData())

    def show_comparison(self, left, right):
        def signature(result):
            manifest, config = result.get('manifest') or {}, result.get('config') or {}
            source = result.get('data_sha256', manifest.get('source_sha256', manifest.get('file_hashes')))
            split = manifest.get('split_sha256', manifest.get('split_hash', manifest.get('split_fingerprint')))
            return (result.get('task_type'), result.get('dataset_key'), manifest.get('version', manifest.get('dataset_version')), source, split,
                    result.get('model_name'), config.get('max_trials'), config.get('timeout_seconds'),
                    config.get('seed'), (config.get('model_config') or {}).get('n_jobs'), config.get('model_config'))
        left_signature, right_signature = signature(left), signature(right)
        proven = (left.get('status') == right.get('status') == 'completed'
                  and left.get('task_type') == right.get('task_type') == 'classification'
                  and left_signature == right_signature and all(left_signature[index] is not None
                  for index in (0, 1, 3, 4, 5, 6, 7, 8, 9)))
        self.compare_note.setText('任务、数据哈希、划分、模型、种子与搜索预算一致；仅报告本次验证结果，不推断普遍收益。'
                                 if proven else '可比条件不同或缺少来源/划分/资源证明。以下仅并排查看，不排名、不计算优化收益。')
        fields = [('实验', 'id'), ('任务', 'task_type'), ('数据', 'dataset_key'), ('模型', 'model_name'),
                  ('方法', 'algorithm'), ('状态', 'status'), ('实际耗时 / s', 'duration_seconds')]
        rows = [[label, left.get(key), right.get(key)] for label, key in fields]
        rows.extend([[key, (left.get('metrics') or {}).get(key), (right.get('metrics') or {}).get(key)]
                     for key in ('overall_balanced_accuracy', 'overall_f1_macro', 'overall_log_loss')])
        rows.extend([['数据与划分证明', _json(left_signature), _json(right_signature)],
                     ['预算与配置', _json(left.get('config')), _json(right.get('config'))]])
        fill_table(self.compare_table, rows)
