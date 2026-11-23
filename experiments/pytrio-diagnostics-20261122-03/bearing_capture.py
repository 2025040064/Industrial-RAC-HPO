"""Capture a real SDK request when public bearing metadata is available."""
import json
from pathlib import Path
from official_submission.tests.test_sdk_callbacks import SDKCallbacksTest

root = Path(__file__).resolve().parent / 'bearing'
root.mkdir(exist_ok=False)
SDKCallbacksTest.setUpClass()
try:
    host = SDKCallbacksTest(methodName='test_structured_model_response_and_training_cpu_are_audited')
    captured = {}
    def capture(messages, options):
        captured.update(messages=messages, options=options, task='B')
        return 'diagnostic-local-only', {'choices': [{'message': {'content': 'RAC'}}]}
    host.run_round('B', model_callback=capture, transfer_enabled=None, source_metadata=True)
    with (root / 'prompt-B.json').open('x') as stream:
        json.dump(captured, stream, indent=2, allow_nan=False)
    print('bearing guard available:', json.loads(captured['messages'][0]['content'])['constraint_risks']['bearing_guard_available'])
finally:
    SDKCallbacksTest.doClassCleanups()
