#!/usr/bin/env python3
"""Eval adapter for browser-use 1.0: same executable contract, options and evidence as browser-use-pi's eval/run.mjs
and the browser-use-pydantic 0.3.0 adapter, but driven through the public API a customer uses:

    Agent(task, llm, browser=Browser(cloud...), reasoning=..., workspace=...).run(max_steps, timeout)

The only eval-specific piece is the observer: Session(after_tool=...) records steps and judge screenshots.
"""

import asyncio
import json
import os
import subprocess
import sys
import tarfile
import time
import traceback
from pathlib import Path

ALLOWED = {'reasoning_effort', 'max_context_chars', 'task_timeout_seconds', 'proxy_country_code',
           'browser_timeout_minutes', 'browser_allow_resizing', 'evidence_format', 'research_tools',
           'delivery_review', 'mode'}
INSTRUCTIONS = {
    True: 'Use browser UI, public search and source APIs for research; use files/scripts for processing.',
    False: 'Use browser UI and page evaluation for research. Do not use web search.',
}
INSTRUCTIONS_TAIL = (' Do not read files outside the output workspace or inspect benchmark source, rubrics, judge code,'
                     ' or credentials. Save requested files incrementally in workspace.')


def parse_options(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError('options must be an object')
    unknown = set(value) - ALLOWED
    if unknown:
        raise ValueError(f'Unknown option: {sorted(unknown)[0]}')
    o = {'reasoning_effort': 'medium', 'max_context_chars': 800_000, 'task_timeout_seconds': 1700,
         'proxy_country_code': 'us', 'browser_timeout_minutes': 60, 'mode': 'default', **value}
    if o['reasoning_effort'] not in {'low', 'medium', 'high'}:
        raise ValueError('Invalid reasoning_effort (browser-use 1.0 takes low|medium|high)')
    if not 1 <= o['task_timeout_seconds'] <= 7200:
        raise ValueError('task_timeout_seconds must be 1..7200')
    if o['browser_timeout_minutes'] * 60 <= o['task_timeout_seconds'] + 30:
        raise ValueError('Browser lifetime must exceed task timeout plus 30 seconds')
    if o.get('evidence_format') not in (None, 'findings'):
        raise ValueError('evidence_format must be findings when provided')
    if o.get('delivery_review'):
        raise ValueError('delivery_review is not implemented in this adapter')
    if 'browser_allow_resizing' in o:
        raise ValueError('browser_allow_resizing is not a browser-use 1.0 option')
    return o


def clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    marker = f'...[at least {len(text) - limit} characters omitted from the middle]...'
    budget = limit - len(marker)
    head = budget // 3
    return text[:head] + marker + text[-(budget - head):]


async def main() -> int:
    env = os.environ
    workspace = Path(env['EVAL_WORKSPACE']).resolve()
    result_path = Path(env['EVAL_RESULT_PATH']).resolve()
    envelope = {'status': 'failed', 'final_output': '', 'self_reported_success': None,
                'error': 'Harness did not start', 'metrics': {}, 'artifacts': [], 'metadata': {}}
    agent = None
    span_cm = None
    Laminar = None
    try:
        options = parse_options(json.loads(env.get('EVAL_OPTIONS_JSON') or '{}'))
        if int(env['EVAL_TIMEOUT_MINUTES']) * 60 < options['task_timeout_seconds'] + 90:
            raise ValueError('Platform timeout must exceed task timeout by at least 90 seconds')
        if not env.get('EVAL_MODEL_API_KEY') or not env.get('BROWSER_USE_API_KEY'):
            raise ValueError('Model and browser credentials are required')
        task = json.loads(Path(env['EVAL_TASK_PATH']).read_text())
        findings = options.get('evidence_format') == 'findings'
        model_name = env['EVAL_MODEL'].removeprefix('openai/')
        os.environ.update(OPENAI_API_KEY=env['EVAL_MODEL_API_KEY'], ANONYMIZED_TELEMETRY='false',
                          BH_TAB_MARKER='0', BH_OPEN_LIVE_URL='0', PYDANTIC_AI_NO_BANNER='1')

        try:
            from lmnr import Laminar as _Laminar

            if env.get('LMNR_PROJECT_API_KEY'):
                _Laminar.initialize(project_api_key=env['LMNR_PROJECT_API_KEY'])
                Laminar = _Laminar
                span_cm = Laminar.start_as_current_span(
                    name='browser_use_v1', input={'task': task, 'options': options, 'model': model_name},
                    parent_span_context=env.get('LMNR_SPAN_CONTEXT') or None)
                span_cm.__enter__()
        except Exception as e:  # telemetry must never fail the task
            print(f'Laminar unavailable: {e}', file=sys.stderr)

        from browser_harness import helpers as bh
        from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse

        import browser_use.agent.service as service
        from browser_use import Agent, Browser
        from browser_use.agent.loop import Session, thinking_and_text

        output_dir = workspace / 'agent_outputs'
        output_dir.mkdir(parents=True, exist_ok=True)
        shots_dir = workspace / 'judge_screenshots'
        shots_dir.mkdir(parents=True, exist_ok=True)

        steps: list[str] = []
        shots: list[str] = []
        shot_steps: list[int] = []
        shot_errors: list[str] = []
        shot_time = [0.0]
        seen_responses = [0]
        holder: dict = {}
        events = open(workspace / 'events.jsonl', 'a')
        agent_steps = open(workspace / 'agent_steps.txt', 'a')

        def capture() -> bytes:
            import base64

            bh.NAME = agent.browser.name  # the daemon browser-use started for this Browser
            params = {'format': 'png'} if findings else {'format': 'jpeg', 'quality': 70}
            return base64.b64decode(bh.cdp('Page.captureScreenshot', _response_timeout=3.5, **params)['data'])

        observer: dict = {'pending': False, 'task': None}

        async def observe() -> None:
            while observer['pending']:
                observer['pending'] = False
                started, step = time.monotonic(), len(steps)
                try:  # observer screenshot of the agent's attached tab, for the judge only
                    data = await asyncio.wait_for(asyncio.to_thread(capture), 3.5)  # bu-pi observerTimeoutMs
                    shot = shots_dir / f'{len(list(shots_dir.iterdir())) + 1:03d}.{"png" if findings else "jpg"}'
                    shot.write_bytes(data)
                    if findings:
                        shots.append(str(shot.relative_to(workspace)))
                        shot_steps.append(step)
                except Exception as e:  # noqa: BLE001
                    if len(shot_errors) < 20:
                        shot_errors.append(str(e)[:500])
                shot_time[0] += time.monotonic() - started

        async def after_tool(name: str, args: dict, r: dict) -> None:
            session = holder['session']
            holder.setdefault('browser_id', agent.browser.id)
            for m in session.messages[seen_responses[0]:]:
                if isinstance(m, ModelResponse):
                    for kind, content in thinking_and_text(m):
                        steps.append(f'{kind}: {clip(content, 4000)}')
                        events.write(json.dumps({'type': 'message', 'kind': kind, 'content': content}) + '\n')
            seen_responses[0] = len(session.messages)
            result = {'output': r['output'], 'error': r['error'], 'images': len(r['images'])}
            steps.append(f'{name}: {clip(json.dumps(args), 2000)}\nresult: {clip(json.dumps(result), 20000)}')
            events.write(json.dumps({'type': 'tool', 'name': name, 'args': args, 'result': result}) + '\n')
            agent_steps.write(f'{name}{" ERROR" if r["error"] else ""}\n{json.dumps(result)}\n')
            events.flush()
            agent_steps.flush()
            observer['pending'] = True  # bu-pi Observer: one capture in flight, latest event wins, never blocks
            if observer['task'] is None or observer['task'].done():
                observer['task'] = asyncio.create_task(observe())

        def eval_session(**kw):  # the observer hook; everything else is Agent.run's own Session
            holder['session'] = Session(after_tool=after_tool, **kw)
            return holder['session']

        service.Session = eval_session

        browser = Browser(cloud_proxy_country_code=options['proxy_country_code'] or None,
                          cloud_timeout=options['browser_timeout_minutes'])
        prompt = task['confirmed_task'] + (f'\nStarting website: {task["website"]}' if task.get('website') else '')
        agent = Agent(prompt, f'openai-responses:{model_name}', browser=browser, reasoning=options['reasoning_effort'],
                      mode=options['mode'], workspace=output_dir, web_search=False,
                      max_context_chars=options['max_context_chars'],  # bu-pi maxContextChars, same compaction trigger
                      extend_system_message=INSTRUCTIONS[findings] + INSTRUCTIONS_TAIL)
        res = await agent.run(max_steps=int(env.get('EVAL_MAX_STEPS') or 100),
                              timeout=options['task_timeout_seconds'])
        if observer['task']:
            observer['pending'] = False
            await asyncio.gather(observer['task'], return_exceptions=True)
        events.close()
        agent_steps.close()

        evidence = {}
        if findings:
            ev_path = workspace / 'findings-evidence.json'
            subprocess.run([sys.executable, str(Path(__file__).with_name('findings.py')), str(output_dir), str(ev_path)],
                           check=True, timeout=300)
            evidence = {**json.loads(ev_path.read_text()), 'steps': steps, 'judge_screenshots': shots,
                        'judge_screenshot_steps': shot_steps, 'timed_out': res.status == 'timeout'}
        (workspace / 'final_message.txt').write_text(res.text)
        (workspace / 'messages.json').write_bytes(ModelMessagesTypeAdapter.dump_json(res.messages, indent=1))
        (workspace / 'sdk-result.json').write_text(json.dumps({
            'status': res.status, 'text': res.text, 'steps': res.steps, 'usage': res.usage, 'cost': res.cost_usd,
            'success': res.success, 'partial': res.partial, 'error': res.error, 'duration_s': res.duration_s},
            indent=2, default=str))
        files = sorted(str(p.relative_to(workspace)) for d in (output_dir, shots_dir) for p in d.rglob('*')
                       if p.is_file() and '.browser-use' not in p.parts)
        envelope = {
            'status': 'failed' if res.status == 'error' else 'completed',
            'final_output': res.text,
            'self_reported_success': res.success,
            'error': res.error,
            'metrics': {'steps': res.steps, 'duration_seconds': res.duration_s, 'input_tokens': res.usage['input'],
                        'output_tokens': res.usage['output'], 'cached_input_tokens': res.usage['cache_read'],
                        'cache_write_tokens': res.usage.get('cache_write', 0),
                        'total_tokens': res.usage['input'] + res.usage['output'], 'total_cost': res.cost_usd},
            'artifacts': files + ['events.jsonl', 'agent_steps.txt', 'final_message.txt', 'sdk-result.json',
                                  'messages.json'],
            'metadata': {**evidence, 'stop_reason': res.status, 'browser': {'id': holder.get('browser_id')}, 'options': options,
                         'python': sys.version.split()[0], 'model': model_name, 'usage': res.usage,
                         'screenshot_errors': len(shot_errors), 'screenshot_error_details': shot_errors,
                         'screenshot_time_ms': int(shot_time[0] * 1000), 'retries': 0, 'harness': 'browser-use-v1'},
        }
    except Exception as e:  # noqa: BLE001
        envelope['error'] = f'{type(e).__name__}: {e}'
        envelope['metadata']['failure_class'] = 'harness-or-provider'
        traceback.print_exc()
    finally:
        if agent is not None:
            try:  # run() already stopped the browser; this is the safety net for an exception before/inside it
                await agent.close()
            except Exception as e:  # noqa: BLE001
                envelope['metadata'].setdefault('cleanup_errors', []).append(f'close: {e}')
        audit = workspace / 'agent_outputs' / '.browser-use'
        if audit.is_dir():  # Actions skips dotfiles; ship REPL cells/logs as one visible archive
            try:
                with tarfile.open(workspace / 'sdk-audit.tar.gz', 'w:gz') as tar:
                    tar.add(audit, arcname='.browser-use')
                envelope['artifacts'].append('sdk-audit.tar.gz')
            except Exception as e:  # noqa: BLE001
                envelope['metadata']['sdk_audit_archive_error'] = str(e)
        result_path.write_text(json.dumps(envelope, indent=2, default=str) + '\n')
        if span_cm is not None:
            try:
                Laminar.set_span_output(envelope)
                span_cm.__exit__(None, None, None)
                Laminar.flush()
                Laminar.shutdown()
            except Exception:  # noqa: BLE001
                pass
    return 1 if envelope['status'] == 'failed' else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
