from pathlib import Path
import os
import subprocess
import sys
import threading
import time

import psutil
import pytest

from src.native_ocr.worker import NativeOcrWorker


FAKE = Path(__file__).with_name('fake_v272_ocr_worker.py')


def make_worker(mode):
    return NativeOcrWorker([sys.executable, str(FAKE), mode], ready_timeout_s=1.0)


@pytest.mark.parametrize('mode', ['no-read', 'silent', 'partial', 'malformed', 'wrong-id', 'missing-id'])
def test_transport_rejects_invalid_or_timed_out_requests(mode):
    worker = make_worker(mode)
    try:
        assert worker.is_available()
        started = time.monotonic()
        result = worker.request({'image_base64': 'x' * (1024 * 1024)}, timeout_s=0.35)
        assert result['error_kind'] == 'transport'
        assert time.monotonic() - started < 1.25
        assert worker.stats()['transport_failures'] == 1
    finally:
        worker.shutdown()


def test_ready_timeout_opens_breaker_without_repeated_startup():
    worker = NativeOcrWorker([sys.executable, str(FAKE), 'late-ready'], ready_timeout_s=0.2)
    try:
        assert not worker.is_available()
        assert 'circuit breaker' in worker.unavailable_reason()
        assert not worker.is_available()
        assert worker.stats()['starts'] == 1
    finally:
        worker.shutdown()


def test_consecutive_transport_failures_open_breaker():
    worker = make_worker('wrong-id')
    try:
        for _ in range(3):
            assert worker.request({}, timeout_s=1)['error_kind'] == 'transport'
        assert worker.request({}, timeout_s=1)['error_kind'] == 'unavailable'
        assert worker.stats()['starts'] == 3
        assert worker.stats()['consecutive_failures'] == 3
    finally:
        worker.shutdown()


@pytest.mark.skipif(os.name != 'nt', reason='Windows job object assignment')
def test_job_assignment_failure_keeps_worker_unavailable(monkeypatch):
    def fail_assignment(_process):
        raise OSError('simulated job assignment failure')

    monkeypatch.setattr('src.native_ocr.worker.WorkerJob', fail_assignment)
    worker = make_worker('stderr')
    try:
        assert not worker.is_available()
        assert 'job assignment failure' in worker.unavailable_reason()
        assert worker.stats()['starts'] == 0
    finally:
        worker.shutdown()


def test_stderr_is_drained_and_application_errors_are_distinct():
    for mode, status in [('stderr', 'ok'), ('application-error', 'error')]:
        worker = make_worker(mode)
        try:
            assert worker.request({}, timeout_s=2)['status'] == status
            assert worker.stats()['transport_failures'] == 0
        finally:
            worker.shutdown()


def test_concurrent_shutdown_interrupts_pending_response():
    worker = make_worker('silent')
    response = []
    assert worker.is_available()
    thread = threading.Thread(target=lambda: response.append(worker.request({}, timeout_s=5)), daemon=True)
    thread.start()
    deadline = time.monotonic() + 1
    while worker.stats()['requests'] == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    worker.shutdown()
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert response[0]['status'] == 'error'


@pytest.mark.skipif(os.name != 'nt', reason='Windows job objects own Windows OCR workers')
def test_parent_os_exit_does_not_orphan_worker():
    source = (
        'import os,sys; from src.native_ocr.worker import NativeOcrWorker; '
        'w=NativeOcrWorker([sys.executable,sys.argv[1],"silent"]); '
        'assert w.is_available(),w.unavailable_reason(); '
        'print(w._transport.process.pid,flush=True); os._exit(0)'
    )
    parent = subprocess.run([sys.executable, '-c', source, str(FAKE)], timeout=8,
                            capture_output=True, text=True, check=True)
    pid = int(parent.stdout.strip())
    try:
        process = psutil.Process(pid)
        process.wait(timeout=2)
    except psutil.NoSuchProcess:
        pass
