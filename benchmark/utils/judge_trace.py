"""Scoped, thread-safe capture of security judge requests for human review."""
from contextlib import contextmanager
from copy import deepcopy
from contextvars import ContextVar
from datetime import datetime, timezone

_active = ContextVar('security_judge_traces', default=None)


@contextmanager
def capture_judges():
    traces = []
    token = _active.set(traces)
    try:
        yield traces
    finally:
        _active.reset(token)


def record_judge(request, *, response=None, raw_output=None, error=None):
    traces = _active.get()
    if traces is not None:
        traces.append({'request': deepcopy(request), 'response': deepcopy(response), 'raw_output': raw_output,
                       'error': error, 'recorded_at': datetime.now(timezone.utc).isoformat(),
                       'model': request['model']})
