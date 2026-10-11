"""Coalesced calendar loading; dispatch must enqueue callbacks on the UI thread."""

from threading import Thread


class EventLoader:
    """Run one load at a time and deliver only the most recently requested key.

    request(), close(), and dispatched callbacks belong to the caller's main
    thread. The worker only computes a result and queues its completion.
    """

    def __init__(self, loader, dispatch, on_result):
        self._loader = loader
        self._dispatch = dispatch
        self._on_result = on_result
        self._active = None
        self._pending = None
        self._latest = None
        self._closed = False

    def request(self, key, lo, hi, data):
        if self._closed:
            return
        request = (key, lo, hi, data)
        self._latest = key
        if self._active is not None:
            if self._active[0][0] == key:
                self._pending = None
            else:
                self._pending = request
            return
        self._start(request)

    def close(self):
        self._closed = True
        self._pending = None
        self._latest = None
        # Do not wait for filesystem I/O during popup destruction.

    def _start(self, request):
        def work():
            issues = []
            try:
                events = list(self._loader(request[1], request[2], request[3],
                                           issues=issues))
            except Exception as exc:
                events = []
                issues.append("Unable to load calendar events: " + str(exc))
            self._dispatch(lambda: self._finish(request, worker, events, issues))

        worker = Thread(target=work, name="calendar-events", daemon=True)
        self._active = (request, worker)
        worker.start()

    def _finish(self, request, worker, events, issues):
        # dispatch queues rather than running inline. Join prevents a new
        # worker overlapping the tail of the old dispatch call.
        worker.join()
        if self._active is None or self._active[1] is not worker:
            return
        self._active = None
        if self._closed:
            return
        pending = self._pending
        self._pending = None
        if request[0] == self._latest:
            self._on_result(request[0], events, issues)
        # on_result can request another load or close the popup itself.
        if not self._closed and self._active is None and pending is not None:
            if pending[0] == self._latest:
                self._start(pending)
