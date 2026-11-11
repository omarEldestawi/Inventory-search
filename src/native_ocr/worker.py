"""Supervised line-delimited transport for the native Windows OCR worker."""

from collections import deque
import json
import os
import queue
import subprocess
import threading
import time
import uuid

from .windows_job import WorkerJob


READY_TIMEOUT_S = 5.0
REQUEST_TIMEOUT_S = 8.0
MAX_REQUEST_TIMEOUT_S = 20.0
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


def _error(reason, kind='transport'):
    return {'status': 'error', 'error': reason, 'error_kind': kind, 'lines': []}


class _Transport:
    def __init__(self, command):
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            self.job = WorkerJob(self.process) if os.name == 'nt' else None
        except OSError:
            self.process.kill()
            self.process.wait(timeout=0.5)
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                stream.close()
            raise
        self.stopped = threading.Event()
        self._close_lock = threading.Lock()
        self._closed = False
        self.outgoing = queue.Queue(maxsize=1)
        self.incoming = queue.Queue(maxsize=4)
        self.stderr = deque(maxlen=8)
        self.threads = [threading.Thread(target=target, daemon=True)
                        for target in (self._write, self._read, self._drain_stderr)]
        for thread in self.threads:
            thread.start()

    def _signal(self, item):
        try:
            self.incoming.put_nowait(item)
        except queue.Full:
            self.stopped.set()

    def _write(self):
        try:
            with self.process.stdin as stream:
                while not self.stopped.is_set():
                    try:
                        data = self.outgoing.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    stream.write(data)
                    stream.flush()
        except (OSError, ValueError) as exc:
            self._signal(exc)

    def _read(self):
        with self.process.stdout as stream:
            try:
                while not self.stopped.is_set():
                    line = stream.readline(_MAX_RESPONSE_BYTES + 1)
                    if not line or len(line) > _MAX_RESPONSE_BYTES or not line.endswith(b'\n'):
                        self._signal(RuntimeError('OCR worker closed or exceeded the response limit'))
                        return
                    self._signal(line.strip())
            except (OSError, ValueError) as exc:
                self._signal(exc)

    def _drain_stderr(self):
        with self.process.stderr as stream:
            while not self.stopped.is_set():
                chunk = stream.read1(4096)
                if not chunk:
                    return
                self.stderr.append(chunk)

    def receive(self, deadline):
        while not self.stopped.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('OCR worker deadline expired')
            try:
                result = self.incoming.get(timeout=min(0.05, remaining))
            except queue.Empty:
                continue
            if isinstance(result, Exception):
                raise result
            return result
        raise RuntimeError('OCR worker transport stopped')

    def close(self):
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        self.stopped.set()
        if self.job is not None:
            self.job.close()
        if self.process.poll() is None:
            self.process.kill()
        deadline = time.monotonic() + 0.5
        try:
            self.process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            return
        for thread in self.threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))


class NativeOcrWorker:
    def __init__(self, command=None, ready_timeout_s=READY_TIMEOUT_S):
        self.command = command
        self.ready_timeout_s = min(float(ready_timeout_s), READY_TIMEOUT_S)
        self._requests = threading.Lock()
        self._lifecycle = threading.Lock()
        self._transport = None
        self._shutdown_generation = 0
        self._reason = None
        self._failures = 0
        self._stats = {'starts': 0, 'requests': 0, 'transport_failures': 0, 'ready_s': None}
        self._latency = deque(maxlen=100)

    def unavailable_reason(self):
        if os.getenv('EPO_DISABLE_NATIVE_OCR', '').lower() in {'1', 'true', 'yes'}:
            return 'Native OCR disabled by EPO_DISABLE_NATIVE_OCR'
        if not self.command:
            return 'Native OCR worker executable is missing'
        return self._reason

    def _discard(self, transport):
        with self._lifecycle:
            if self._transport is not transport:
                return
            self._transport = None
        transport.close()

    def _ready(self, deadline, generation):
        reason = self.unavailable_reason()
        if reason:
            raise RuntimeError(reason)
        old = None
        with self._lifecycle:
            if generation != self._shutdown_generation:
                raise RuntimeError('OCR worker shut down')
            if self._transport is not None:
                if self._transport.process.poll() is None and not self._transport.stopped.is_set():
                    return self._transport
                old, self._transport = self._transport, None
        if old is not None:
            old.close()
        if deadline <= time.monotonic():
            raise TimeoutError('OCR request expired before worker startup')
        started = time.monotonic()
        transport = None
        try:
            transport = _Transport(self.command)
            with self._lifecycle:
                if generation == self._shutdown_generation:
                    self._transport = transport
            if self._transport is not transport:
                transport.close()
                raise RuntimeError('OCR worker shut down during startup')
            self._stats['starts'] += 1
            if transport.receive(min(deadline, started + self.ready_timeout_s)) != b'__READY__':
                raise RuntimeError('Invalid OCR worker READY message')
            self._stats['ready_s'] = time.monotonic() - started
            return transport
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            if transport is not None:
                self._discard(transport)
            if generation == self._shutdown_generation:
                self._reason = f'Native OCR startup failed (circuit breaker): {exc}'
            raise

    def is_available(self):
        generation = self._shutdown_generation
        if self.unavailable_reason() or not self._requests.acquire(timeout=self.ready_timeout_s):
            return False
        try:
            self._ready(time.monotonic() + self.ready_timeout_s, generation)
            return True
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
            return False
        finally:
            self._requests.release()

    def request(self, payload, timeout_s=REQUEST_TIMEOUT_S):
        started = time.monotonic()
        timeout = max(0.0, min(float(timeout_s), MAX_REQUEST_TIMEOUT_S))
        deadline = started + timeout
        generation = self._shutdown_generation
        if not self._requests.acquire(timeout=timeout):
            return _error('OCR request deadline expired while waiting for the worker')
        try:
            reason = self.unavailable_reason()
            if reason:
                return _error(reason, 'unavailable')
            request_id = uuid.uuid4().hex
            data = (json.dumps(dict(payload, request_id=request_id), ensure_ascii=True) + '\n').encode('utf-8')
            if deadline <= time.monotonic():
                return _error('OCR request deadline expired before sending')
            transport = self._ready(deadline, generation)
            try:
                self._stats['requests'] += 1
                transport.outgoing.put_nowait(data)
                response = json.loads(transport.receive(deadline))
                if (not isinstance(response, dict) or response.get('request_id') != request_id
                        or response.get('status') not in {'ok', 'error'} or not isinstance(response.get('lines'), list)):
                    raise ValueError('Invalid or mismatched OCR response')
            except (OSError, RuntimeError, ValueError, queue.Full) as exc:
                self._discard(transport)
                self._stats['transport_failures'] += 1
                if generation == self._shutdown_generation:
                    self._failures += 1
                    if self._failures >= 3:
                        self._reason = f'Native OCR transport circuit breaker: {exc}'
                return _error(str(exc))
            self._failures = 0
            self._latency.append(time.monotonic() - started)
            return response
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            return _error(self._reason or str(exc), 'unavailable')
        finally:
            self._requests.release()

    def shutdown(self):
        with self._lifecycle:
            self._shutdown_generation += 1
            transport, self._transport = self._transport, None
        if transport is not None:
            transport.close()

    def stats(self):
        return dict(self._stats, consecutive_failures=self._failures, latencies_s=list(self._latency))

    def reset_breaker(self):
        self.shutdown()
        self._reason = None
        self._failures = 0
