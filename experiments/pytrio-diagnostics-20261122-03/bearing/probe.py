"""Sample a captured local SDK prompt using the submitted sampler."""
import json
import sys
import time
from pathlib import Path

import pytrio as trio
from rac_hpo.contest.stage3_controls import parse_decision

root = Path(__file__).resolve().parent
task = sys.argv[1]
request = json.loads((root / f'prompt-{task}.json').read_text())
start = time.monotonic()
result = {'task': task, 'prompt_source': 'local actual SDK request',
          'sampler_path': 'trio://run_2wehwhow3d8t/sampler_weights/rac-hpo-lora-20261117',
          'stop': ['<|im_end|>'], 'status': 'started'}
try:
    sampler = trio.ServiceClient().create_sampling_client('Qwen/Qwen3.5-4B', model_path=result['sampler_path'])
    tokenizer = sampler.get_tokenizer()
    rendered = tokenizer.apply_chat_template(request['messages'], tokenize=False,
                                              add_generation_prompt=True, enable_thinking=False)
    ids = tokenizer.encode(rendered, add_special_tokens=False)
    sequence = sampler.sample(prompt=trio.ModelInput.from_ints(ids),
                              sampling_params=trio.SamplingParams(max_tokens=request['options']['max_tokens'],
                                  temperature=0, seed=42, stop=result['stop']), num_samples=1).result().sequences[0]
    result.update(status='ok', input_tokens=len(ids), text=sequence.text,
                  token_ids=sequence.tokens, stop_reason=str(sequence.stop_reason),
                  parsed=parse_decision(sequence.text))
except Exception as exc:
    result.update(status='error', error_type=type(exc).__name__)
finally:
    result['elapsed_seconds'] = time.monotonic() - start
    with (root / f'live-{task}.json').open('x') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
print(result['task'], result['status'], result.get('parsed', {}).get('action'), flush=True)
