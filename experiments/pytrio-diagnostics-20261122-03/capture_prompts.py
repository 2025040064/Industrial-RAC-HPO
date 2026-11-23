"""Capture actual local SDK requests with public A/B/C checkpoints; no remote calls."""
import json
from pathlib import Path

from official_submission.tests.test_sdk_callbacks import SDKCallbacksTest

root = Path(__file__).resolve().parent
SDKCallbacksTest.setUpClass()
try:
    host = SDKCallbacksTest(methodName='test_structured_model_response_and_training_cpu_are_audited')
    for task in ('A', 'B', 'C'):
        captured = {}
        def capture(messages, options):
            captured.update(messages=messages, options=options)
            return 'diagnostic-local-only', {'choices': [{'message': {'content': 'RAC'}}]}
        state, _ = host.run_round(task, model_callback=capture, transfer_enabled=None)
        captured['task'] = task
        with (root / f'prompt-{task}.json').open('x', encoding='utf-8') as stream:
            json.dump(captured, stream, ensure_ascii=False, indent=2, allow_nan=False)
        print(task, len(captured['messages'][0]['content']), flush=True)
finally:
    SDKCallbacksTest.doClassCleanups()
