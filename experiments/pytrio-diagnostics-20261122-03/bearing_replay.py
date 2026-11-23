"""Replay the live B decision with verified bearing metadata."""
import json
from pathlib import Path
import shutil
from official_submission.tests.test_sdk_callbacks import SDKCallbacksTest

root = Path(__file__).resolve().parent / 'bearing'
request = json.loads((root / 'prompt-B.json').read_text())
sampled = json.loads((root / 'live-B.json').read_text())
if sampled['status'] != 'ok':
    raise SystemExit('No completed sampler response')
SDKCallbacksTest.setUpClass()
try:
    host = SDKCallbacksTest(methodName='test_structured_model_response_and_training_cpu_are_audited')
    def respond(messages, options):
        if messages != request['messages'] or options != request['options']:
            raise ValueError('SDK prompt or options changed')
        return 'diagnostic-replayed-real-sample', {'choices': [{'message': {'content': sampled['text']}}]}
    state, sent = host.run_round('B', model_callback=respond, transfer_enabled=None, source_metadata=True)
    target = root / 'replay'
    target.mkdir(exist_ok=False)
    shutil.copyfile(state / 'selection-audit.jsonl', target / 'selection-audit.jsonl')
    shutil.copyfile(state / 'rac-round.json', target / 'rac-round.json')
    shutil.copyfile(state.parent / 'measured.npz', target / 'candidate.npz')
    (target / 'round-complete.json').write_text(json.dumps(sent['round_complete'], indent=2))
    row = json.loads((target / 'selection-audit.jsonl').read_text())
    print('action', row['decision']['model_action'], 'bearing_gate', row['gates']['bearing_gate'],
          'accepted', row['accepted'], flush=True)
finally:
    SDKCallbacksTest.doClassCleanups()
