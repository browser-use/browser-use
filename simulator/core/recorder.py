"""Per-step trajectory recorder + the recording LLM proxy.

Layout written per task::

  <source>__<task_id>/
    meta.json          task id/site/source, question, start url, status, final
                       answer, and the reference answer (ground truth)
    tool_schema.json   the structured-output (tool) schema used each step
    history.json       browser-use AgentHistoryList (structured actions/states)
    step_001/
      messages.json    EXACT LLM input context (reloadable list[BaseMessage])
      output.json      the LLM output for that step (thinking + action taken)
      screenshot.jpg   page at the start of the step
      state.json       url + title at the start of the step
    step_002/ ...

``messages.json`` is the complete, self-contained context the agent saw, so every
step's action can be re-predicted offline with no browser. ``meta.answer`` +
``meta.reference_answer`` + the screenshots feed the WebVoyager success judge.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from pydantic import TypeAdapter

from browser_use.llm.messages import BaseMessage
from browser_use.llm.schema import SchemaOptimizer
from simulator.core.batching import BatchLLMProxy
from simulator.tasks import WebVoyagerTask

_MSGS = TypeAdapter(list[BaseMessage])


class TrajectoryRecorder:
	"""Writes one folder per task and one sub-folder per step."""

	def __init__(self, task_dir: Path, task: WebVoyagerTask):
		self.dir = task_dir
		self.dir.mkdir(parents=True, exist_ok=True)
		self.step = 0
		self._schema_saved = False
		# Keep meta in memory so finalize() can persist the final status without re-reading the
		# file (a read failure there would leave the task statusless -> retried forever).
		self._meta = {
			'id': task.id,
			'site': task.site,
			'source': task.source,
			'question': task.question,
			'start_url': task.start_url,
			'reference_answer': task.reference_answer,
			'reference_type': task.reference_type,
			'reference_notice': task.reference_notice,
		}
		self._write_meta()

	def _write_meta(self) -> None:
		"""Atomically write meta.json (tmp + rename) so a concurrent resume check never sees a partial file."""
		try:
			tmp = self.dir / 'meta.json.tmp'
			tmp.write_text(json.dumps(self._meta, ensure_ascii=False, indent=2))
			tmp.replace(self.dir / 'meta.json')
		except Exception:  # noqa: BLE001
			pass

	def _stepdir(self) -> Path:
		d = self.dir / f'step_{self.step:03d}'
		d.mkdir(exist_ok=True)
		return d

	async def on_step_start(self, agent) -> None:
		"""Capture the observation (screenshot + url) the agent is about to act on."""
		self.step += 1
		d = self._stepdir()
		try:
			cdp = await agent.browser_session.get_or_create_cdp_session()
			# JPEG (not PNG) keeps the per-step capture light so it doesn't starve the
			# event loop / CDP while N headed browsers build their DOM+AX trees concurrently.
			shot = await cdp.cdp_client.send.Page.captureScreenshot(
				params={'format': 'jpeg', 'quality': 60}, session_id=cdp.session_id
			)
			(d / 'screenshot.jpg').write_bytes(base64.b64decode(shot['data']))
			info = await cdp.cdp_client.send.Runtime.evaluate(
				params={'expression': 'JSON.stringify({url:location.href,title:document.title})', 'returnByValue': True},
				session_id=cdp.session_id,
			)
			(d / 'state.json').write_text(info.get('result', {}).get('value') or '{}')
		except Exception as e:  # noqa: BLE001
			(d / 'state.json').write_text(json.dumps({'capture_error': str(e)[:200]}))

	def record_llm(self, messages, output_format, completion) -> None:
		"""Capture the exact LLM context + output for the current step."""
		d = self._stepdir()
		(d / 'messages.json').write_text(
			json.dumps({'messages': _MSGS.dump_python(messages, mode='json')}, ensure_ascii=False, indent=2)
		)
		try:
			(d / 'output.json').write_text(completion.model_dump_json(indent=2))
		except Exception:  # noqa: BLE001
			(d / 'output.json').write_text(json.dumps({'raw': str(completion)}, ensure_ascii=False))
		if not self._schema_saved:
			try:
				schema = SchemaOptimizer.create_optimized_json_schema(output_format)
				(self.dir / 'tool_schema.json').write_text(
					json.dumps({'name': output_format.__name__, 'schema': schema}, ensure_ascii=False, indent=2)
				)
			except Exception as e:  # noqa: BLE001
				(self.dir / 'tool_schema.json').write_text(json.dumps({'error': str(e)[:200]}))
			self._schema_saved = True

	def finalize(self, agent, status: str, success: bool | None) -> None:
		try:
			agent.history.save_to_file(self.dir / 'history.json')
		except Exception:  # noqa: BLE001
			pass
		answer = None
		try:
			answer = agent.history.final_result()
		except Exception:  # noqa: BLE001
			pass
		self._meta.update({'status': status, 'agent_self_reported_success': success, 'num_steps': self.step, 'answer': answer})
		self._write_meta()


class RecordingProxy(BatchLLMProxy):
	"""BatchLLMProxy that also records each agent-step's LLM input/output."""

	def __init__(self, coordinator, recorder: TrajectoryRecorder):
		super().__init__(coordinator)
		self._rec = recorder

	async def ainvoke(self, messages, output_format=None, **kwargs):
		result = await super().ainvoke(messages, output_format=output_format, **kwargs)
		try:
			# Only the agent's step decision uses an output model with an 'action' field;
			# page-extraction / other calls are skipped so step numbering stays clean.
			if output_format is not None and 'action' in getattr(output_format, 'model_fields', {}):
				self._rec.record_llm(messages, output_format, result.completion)
		except Exception:  # noqa: BLE001
			pass
		return result

	def __getattr__(self, name: str):
		if name in ('_coord', '_rec'):
			raise AttributeError(name)
		return getattr(self._coord.real, name)
