"""Exercise the production queue wrapper with controlled backend operations."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[2] / 'mcp_servers/mail/mcp_servers/mail_server/tools/_meta_tools.py'


def queue_wrapper(dispatch):
    # Load the real wrapper without the service's Python 3.13-only schema dependencies.
    tree = ast.parse(SOURCE.read_text())
    wrapper = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'mail')
    namespace = dict(asyncio=asyncio, MailInput=object, MailOutput=object,
                     _MAIL_OPERATION_QUEUE=asyncio.Lock(), _dispatch_mail=dispatch)
    exec(compile(ast.Module(body=[wrapper], type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace['mail']


@pytest.mark.asyncio
async def test_reads_and_writes_share_queue():
    active = 0
    order = []
    async def dispatch(request):
        nonlocal active
        active += 1
        assert active == 1
        order.append(request.action)
        await asyncio.sleep(0.01)
        active -= 1
    mail = queue_wrapper(dispatch)
    await asyncio.gather(*(mail(SimpleNamespace(action=a)) for a in ['send', 'read', 'delete', 'forward']))
    assert order == ['send', 'read', 'delete', 'forward']


@pytest.mark.asyncio
async def test_cancelled_request_does_not_release_worker_queue():
    started, release = asyncio.Event(), asyncio.Event()
    events = []
    async def dispatch(request):
        events.append(request.action)
        if request.action == 'send':
            started.set()
            await release.wait()
        events.append(request.action + '_done')
    mail = queue_wrapper(dispatch)
    first = asyncio.create_task(mail(SimpleNamespace(action='send')))
    await started.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    second = asyncio.create_task(mail(SimpleNamespace(action='read')))
    await asyncio.sleep(0.01)
    assert events == ['send']
    release.set()
    await second
    assert events == ['send', 'send_done', 'read', 'read_done']
