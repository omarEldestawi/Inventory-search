"""Record timing and extraction evidence for an isolated benchmark build."""

import json
import os
import sys
from pathlib import Path
import time
import threading


def enabled():
    return bool(os.getenv("EPO_BENCH_TRACE_DIR"))


def event(name, **payload):
    directory = os.getenv('EPO_BENCH_TRACE_DIR')
    if directory:
        record = dict(name=name, time_ns=time.perf_counter_ns(), pid=os.getpid(), thread=threading.get_ident(), **payload)
        with (Path(directory) / f'{os.getpid()}-{threading.get_ident()}.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + '\n')


def setup_app(app):
    manifest = os.getenv('EPO_BENCH_INPUTS')
    if not manifest or "--benchmark-batch" not in sys.argv:
        return
    config = json.loads(Path(manifest).read_text(encoding='utf-8-sig'))
    inputs = [entry['path'] for entry in config['catalogs']] + [config['order']['path']]
    output = Path(os.environ['EPO_BENCH_TRACE_DIR']) / 'workbook'
    output.mkdir()
    app.output_dir_var.set(str(output))

    def drop():
        event('drop')
        app.add_files(inputs)
        app.after(250, click_run)

    def click_run():
        event('run_clicked', in_progress=bool(app._catalogs_inspecting))
        app.run_button.invoke()

    app.after(500, drop)
