"""One state observer per app; SSE clients consume coalesced snapshots."""
import asyncio
from copy import deepcopy
import json
import threading
import time
import uuid


class EventStream:
    def __init__(self, runtime):
        self.rt = runtime
        self.epoch = uuid.uuid4().hex
        self.condition = threading.Condition()
        self.stop = threading.Event()
        self.thread = None
        self.state = None
        self.version = 0
        self.seq = 0
        self.error = False

    def start(self):
        self.poll()
        self.thread = threading.Thread(target=self._observe, name='mathlens-events', daemon=True)
        self.thread.start()

    def _observe(self):
        while not self.stop.wait(.5):
            try:self.poll()
            except Exception:
                # Saved data remains authoritative; close clients so reconnect
                # takes a fresh snapshot, without exposing paths/tool exceptions.
                with self.condition:
                    self.error = True
                    self.condition.notify_all()

    def poll(self):
        revision = self.rt.workspace.revision()
        value = dict(tasks=self.rt.tasks.read(), preparation=self.rt.local.preparation(),
                     resource_tokens={'personal':self.epoch+':'+str(revision[0]), 'library':self.epoch+':'+str(revision[1])})
        with self.condition:
            self.error = False
            if value != self.state:
                self.state = value
                self.version += 1
                self.condition.notify_all()

    def close(self):
        self.stop.set()
        with self.condition:self.condition.notify_all()
        if self.thread:self.thread.join(timeout=5)

    def _current(self, version=None, timeout=15):
        with self.condition:
            if version is not None:
                self.condition.wait_for(lambda: self.version != version or self.stop.is_set() or self.error, timeout)
            if self.error:raise RuntimeError('后台状态暂不可用，请重新连接')
            return self.version, deepcopy(self.state)

    def frame(self, event, payload):
        with self.condition:
            self.seq += 1
            value = dict(epoch=self.epoch, seq=self.seq, **payload)
        return 'id: '+self.epoch+':'+str(value['seq'])+'\nevent: '+event+'\ndata: '+json.dumps(value, ensure_ascii=False, separators=(',', ':'))+'\n\n'

    async def stream(self, request):
        # Last-Event-ID intentionally does not request replay. Every connection
        # receives a new complete small snapshot, including after server restart.
        try:
            version, previous = self._current()
            request.state.heartbeat = time.monotonic()
            yield 'retry: 3000\n\n'+self.frame('snapshot', previous)
            while not self.stop.is_set() and not await request.is_disconnected():
                latest, current = await asyncio.to_thread(self._current, version, 1)
                if latest == version:
                    # Short waits make shutdown/disconnect prompt; heartbeat is
                    # infrequent and never triggers a resource read per client.
                    now = time.monotonic()
                    if now-getattr(request.state, 'heartbeat', 0) >= 15:
                        request.state.heartbeat = now
                        yield ': heartbeat\n\n'
                    continue
                if current['tasks'] != previous['tasks']:
                    yield self.frame('tasks.changed', {'tasks':current['tasks']})
                if current['preparation'] != previous['preparation']:
                    yield self.frame('preparation.changed', {'preparation':current['preparation']})
                if current['resource_tokens'] != previous['resource_tokens']:
                    yield self.frame('resources.changed', dict(resources=['papers','questions','practices','knowledge','bank','preferences','profile'], resource_tokens=current['resource_tokens']))
                version, previous = latest, current
        except RuntimeError:
            yield 'event: error\ndata: {"error":"后台状态暂不可用，请重新连接"}\n\n'
