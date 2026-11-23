"""Replay captured real sampler replies through matching actual SDK requests."""
import json
from pathlib import Path
import shutil

from official_submission.tests.test_sdk_callbacks import SDKCallbacksTest

root = Path(__file__).resolve().parent
SDKCallbacksTest.setUpClass()
try:
    host = SDKCallbacksTest(methodName='test_structured_model_response_and_training_cpu_are_audited')
    for task in ('A', 'B', 'C'):
        request = json.loads((root / f'prompt-{task}.json').read_text())
        sampled = json.loads((root / f'live-{task}.json').read_text())
        if sampled['status'] != 'ok':
            print(task, 'no completed sample', flush=True)
            continue
        def respond(messages, options):
            if messages != request['messages'] or options != request['options']:
                raise ValueError('SDK prompt or options changed since sample was captured')
            return 'diagnostic-replayed-real-sample', {'choices': [{'message': {'content': sampled['text']}}]}
        state, sent = host.run_round(task, model_callback=respond, transfer_enabled=None)
        target = root / 'replay' / task
        target.mkdir(parents=True, exist_ok=False)
        shutil.copyfile(state / 'selection-audit.jsonl', target / 'selection-audit.jsonl')
        shutil.copyfile(state / 'rac-round.json', target / 'rac-round.json')
        shutil.copyfile(state.parent / 'measured.npz', target / 'candidate.npz')
        (target / 'round-complete.json').write_text(json.dumps(sent['round_complete'], indent=2))
        audit = json.loads((target / 'selection-audit.jsonl').read_text().splitlines()[-1])
        print(task, audit['decision']['model_action'], 'accepted', audit['accepted'], flush=True)
finally:
    SDKCallbacksTest.doClassCleanups()
