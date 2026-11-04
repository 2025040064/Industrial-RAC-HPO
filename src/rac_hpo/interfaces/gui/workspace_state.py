"""Pure presentation mapping for persisted experiment records and progress snapshots."""

import math


STATUS_LABELS = {
    "running": "运行中", "completed": "已完成", "COMPLETE": "已完成",
    "failed": "失败", "FAIL": "失败", "cancelled": "已取消", "cancelling": "取消中",
    "idle": "就绪", "starting": "准备中",
}


def finite_value(value):
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def search_trials(records):
    """Exclude the pre-run baseline, deduplicate by true number, then order."""
    by_number = {}
    for record in records or []:
        try:
            number = int(record.get("number", record.get("trial_id")))
        except (TypeError, ValueError, OverflowError):
            continue
        if number >= 0:
            by_number[number] = {**record, "number": number}
    return [by_number[number] for number in sorted(by_number)]


def completed_trials(records):
    return [record for record in search_trials(records)
            if record.get("status") in ("completed", "COMPLETE")
            and finite_value(record.get("objective", record.get("value"))) is not None]


def objective_label(experiment):
    if experiment.get("algorithm") in ("tpe_robust", "rac_hpo"):
        return "J", "无量纲"
    return "MAE", experiment.get("target_unit") or "单位未记录"


def objective_value(trial):
    return finite_value(trial.get("objective", trial.get("value")))


def status_label(value):
    return STATUS_LABELS.get(value, str(value) if value else "—")


from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo


@dataclass
class WorkspaceViewState:
    """Display-only context; never identifies the background worker to cancel."""
    context_id: str | None = None
    active_record_id: str | None = None
    selected_ids: set = field(default_factory=set)
    filters: dict = field(default_factory=dict)
    brush: dict = field(default_factory=dict)
    panel_state: dict = field(default_factory=dict)

    def set_context(self, identifier):
        if identifier != self.context_id:
            self.context_id = identifier
            self.active_record_id = None
            self.selected_ids.clear()
            self.brush.clear()
            self.filters.clear()

    def matches(self, record):
        for name, (low, high) in self.brush.items():
            value = finite_value(record.get('params', {}).get(name))
            if value is None or not low <= value <= high:
                return False
        return True


def display_time(value):
    if not value:
        return '—'
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if parsed.tzinfo is None:
            return str(value) + '（时区未记录）'
        return parsed.astimezone(ZoneInfo('Asia/Singapore')).strftime('%Y-%m-%d %H:%M:%S +08:00')
    except (ValueError, TypeError):
        return str(value)


def trial_view_records(snapshot):
    return [{**trial, '_id': f"{snapshot.get('id')}:{trial['number']}",
             'status':status_label(trial.get('status')), 'objective':objective_value(trial),
             'mae':(trial.get('metrics') or {}).get('overall_mae'),
             'decision':(trial.get('selection') or {}).get('method','standard_sampler')}
            for trial in search_trials(snapshot.get('trials',[]))]


def filtered_trial_ids(snapshot,state):
    import json
    query=state.filters.get('query','').strip().casefold()
    fields=state.filters.get('fields',{})
    return {r['_id'] for r in trial_view_records(snapshot)
            if (not query or query in json.dumps(r,ensure_ascii=False,indent=2,default=str).casefold())
            and all(value is None or r.get(key)==value for key,value in fields.items())
            and state.matches(r)}
