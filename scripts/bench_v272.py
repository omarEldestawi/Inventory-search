"""Collect v2.7.2 source timings and evaluate release evidence on Windows."""

import argparse
from collections import Counter
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
from importlib.metadata import distributions
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import time
import unicodedata

import psutil


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


@contextmanager
def launched(command, root, directory, environment=None):
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    state = directory / 'state'
    state.mkdir(exist_ok=False)
    env = dict(os.environ, LOCALAPPDATA=str(state), APPDATA=str(state),
               EPO_CORRECTIONS_DIR=str(state / 'corrections'), PYTHONIOENCODING='utf-8', ENABLE_GEMINI='false')
    env.update(environment or {})
    with (directory / 'stdout.log').open('wb') as stdout, (directory / 'stderr.log').open('wb') as stderr:
        started = time.perf_counter()
        child = psutil.Popen(command, cwd=root, env=env, stdout=stdout, stderr=stderr)
        descendants = set()

        def remember_tree():
            try:
                if child.is_running():
                    descendants.update(child.children(recursive=True))
            except psutil.NoSuchProcess:
                pass

        try:
            yield child, started, remember_tree
        finally:
            remember_tree()
            processes = [*descendants, child]
            for process in processes:
                try:
                    process.kill()
                except psutil.NoSuchProcess:
                    pass
            _, alive = psutil.wait_procs(processes, timeout=5)
            if alive:
                raise RuntimeError(f'Benchmark processes did not exit: {[p.pid for p in alive]}')


def main_window_visible(pid):
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    found = False

    @callback_type
    def visit(window, _):
        nonlocal found
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(window):
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(window, title, len(title))
            found = 'Egyptian Pharma Procurement Optimizer' in title.value
        return not found

    user32.EnumWindows(visit, 0)
    return found


def app_startup(command, root, directory, timeout):
    with launched(command, root, directory) as (child, started, _):
        while not main_window_visible(child.pid):
            if child.poll() is not None:
                raise RuntimeError(f'App exited before showing its main window ({child.returncode})')
            if time.perf_counter() - started >= timeout:
                raise TimeoutError('Main window did not appear before the deadline')
            time.sleep(0.05)
        startup = time.perf_counter() - started
        time.sleep(30)
        processes = [child, *child.children(recursive=True)]
        private = 0
        for process in processes:
            try:
                private += process.memory_info().private
            except psutil.NoSuchProcess:
                if process.pid == child.pid:
                    raise RuntimeError('App exited before the memory sample') from None
        return startup, private


def parse_result(path):
    parts = path.read_text(encoding='utf-8').split('__JSON_RESULT__')
    if len(parts) != 3:
        raise ValueError('Expected one complete catalog result')
    result = json.loads(parts[1])
    if result['count'] != len(result['items']) or result['status'] not in {'complete', 'partial', 'failed', 'unverified'}:
        raise ValueError('Invalid catalog count or status')
    for row in result['items']:
        if not row['name'].strip() or not math.isfinite(row['price']) or row['price'] <= 0:
            raise ValueError('Invalid name or price in catalog result')
        discount = row['discount']
        if discount is not None and (not math.isfinite(discount) or not 0 <= discount <= 1):
            raise ValueError('Invalid discount in catalog result')
    return result


def catalog_trial(command, root, directory, fixture, timeout):
    with launched([*command, '--test-catalog', str(fixture)], root, directory) as (child, started, remember_tree):
        while child.poll() is None:
            remember_tree()
            if time.perf_counter() - started >= timeout:
                raise TimeoutError(f'Catalog CLI timed out for {fixture.name}')
            time.sleep(0.05)
        elapsed = time.perf_counter() - started
        if child.returncode != 0:
            raise RuntimeError(f'Catalog CLI exited with {child.returncode}')
    return elapsed, parse_result(directory / 'stdout.log')


def app(args):
    root = args.root.resolve()
    entry = root / 'app_gui.py'
    fixtures = {key: root / 'tests' / 'fixtures' / name for key, name in (
        ('digital_import_s', 'hayah_shibin.pdf'), ('scanned_import_s', 'test_scanned_page1.pdf'))}
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True, timeout=10).strip()
    executable = Path(sys.executable)
    args.logs.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='app-', dir=args.logs.resolve()))
    record = {
        'schema': 1, 'commit': commit, 'entry_sha256': sha256(entry), 'executable_sha256': sha256(executable),
        'input_sha256': {key: sha256(path) for key, path in fixtures.items()},
        'python': sys.version, 'dependencies': {dist.metadata['Name']: dist.version for dist in distributions()},
        'windows': platform.platform(), 'ocr_policy': args.ocr_policy,
        'catalog_entry_point': '--test-catalog (direct parser CLI)',
        'cache_state': 'fresh application data per process, OS cache not flushed', 'gemini_enabled': False,
        'log_directory': str(run), 'trials': [], 'medians': {},
    }
    command = [str(executable), str(entry)]
    try:
        for index in range(args.trials):
            label = 'first' if index == 0 else 'subsequent'
            directory = run / str(index + 1)
            trial = {'launch': label}
            record['trials'].append(trial)
            trial['startup_s'], trial['private_bytes'] = app_startup(command, root, directory / 'startup', args.timeout)
            for key, fixture in fixtures.items():
                elapsed, result = catalog_trial(command, root, directory / key, fixture, args.timeout)
                if key == 'digital_import_s' and (result['count'] != 571 or result['status'] != 'complete'):
                    raise ValueError('Digital fixture differs from its verified row count or status')
                trial[key] = elapsed
                write_json(directory / key / 'catalog.json', result)
                trial[key + '_rows'] = result['count']
            write_json(args.out, record)
        for label in ('first', 'subsequent'):
            trials = [trial for trial in record['trials'] if trial['launch'] == label]
            if trials:
                record['medians'][label] = {key: statistics.median(trial[key] for trial in trials)
                                            for key in ('startup_s', 'private_bytes', *fixtures)}
    except Exception as exc:
        record['error'] = str(exc)
        raise
    finally:
        write_json(args.out, record)


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def checked_hash(entry, root):
    path = (root / entry['path']).resolve()
    actual = sha256(path)
    if actual != entry['sha256']:
        raise ValueError(f'Input hash does not match manifest: {path}')
    return actual


def run_packaged_trial(args):
    exe = args.exe.resolve()
    directory = args.directory.resolve()
    trace = directory / 'events'
    trace.mkdir(parents=True)
    manifest = read_json(args.inputs)
    input_hashes = [checked_hash(entry, args.inputs.parent) for entry in [*manifest['catalogs'], manifest['order']]]
    environment = {'EPO_BENCH_INPUTS': str(args.inputs.resolve()), 'EPO_BENCH_TRACE_DIR': str(trace)}
    exit_code = None
    try:
        with launched([str(exe), "--benchmark-batch"], exe.parent, directory, environment) as (child, started, remember_tree):
            while child.poll() is None:
                remember_tree()
                if time.perf_counter() - started >= args.timeout:
                    raise TimeoutError(f'Packaged workflow timed out. Raw evidence: {trace}')
                time.sleep(0.05)
            exit_code = child.returncode
    finally:
        events = sorted((event for path in trace.glob('*.jsonl')
                         for event in map(json.loads, path.read_text(encoding='utf-8').splitlines())),
                        key=lambda event: event['time_ns'])
        write_json(directory / 'raw.json', {'executable_sha256': sha256(exe), 'input_sha256': input_hashes,
                                            'gemini_enabled': False, 'exit_code': exit_code, 'events': events})
    if exit_code != 0 or not any(event['name'] == 'saved' for event in events):
        raise RuntimeError(f'Packaged workflow did not save a workbook. Raw evidence: {trace}')

    trial = summarize_trace(events, manifest['catalogs'], args.inputs.parent)
    trial['exit_code'] = exit_code
    trial['saved_workbook'] = os.path.relpath(trial['saved_workbook'], directory)
    write_json(directory / 'trial.json', trial)


def summarize_trace(events, catalogs, inputs_root):
    def matching(name):
        return [event for event in events if event['name'] == name]

    def time_of(name):
        matches = matching(name)
        if len(matches) != 1:
            raise ValueError(f'Expected a single packaged {name} event, found {len(matches)}')
        return matches[0]['time_ns']

    def duration(start, end):
        elapsed = (time_of(end) - time_of(start)) / 1e9
        if elapsed < 0:
            raise ValueError(f'Packaged {end} precedes {start}')
        return elapsed

    def catalog_events(name, path):
        return [event for event in matching(name) if Path(event['path']).resolve() == path]

    observations = []
    visible_times = []
    for entry in catalogs:
        path = (inputs_root / entry['path']).resolve()
        starts = catalog_events('parse_start', path)
        ends = catalog_events('parse_end', path)
        visible = catalog_events('inspection_visible', path)
        if not starts or not ends or not visible:
            raise ValueError(f'Missing packaged inspection events for {path.name}')
        visible_times.append(visible[0]['time_ns'])
        related = [event for event in events if event['name'] in {'ocr_call', 'ocr_worker_start'}
                   and any(start['pid'] == event['pid'] and start['thread'] == event['thread']
                           and start['time_ns'] <= event['time_ns'] <= end['time_ns']
                           for start in starts for end in ends
                           if start['pid'] == end['pid'] and start['thread'] == end['thread'])]
        result = ends[-1]
        verified = []
        for row in result['rows']:
            identity = row.get('source_id') or row.get('_source_id')
            match = re.match(r'^p(\d+)_', identity) if isinstance(identity, str) else None
            if match:
                verified.append({'source_id': identity, 'page': int(match[1]), 'name': row['item_name'],
                                 'price': row['base_price'], 'discount': row['discount_rate']})
        observations.append({'sha256': entry['sha256'], 'parse_starts': len(starts), 'status': result['status'],
                             'accepted_rows': len(result['rows']), 'observed_rows': result['rows'],
                             'verified_rows': verified, 'unresolved_rows': len(result['unresolved']),
                             'unresolved_source_ids': [issue['source_id'] for issue in result['unresolved']],
                             'unresolved': result['unresolved'],
                             'worker_starts': sum(event['name'] == 'ocr_worker_start' for event in related),
                             'ocr_calls': sum(event['name'] == 'ocr_call' for event in related)})

    drop = time_of('drop')
    clicked = time_of('run_clicked')
    if not matching('run_clicked')[0]['in_progress'] or not drop <= clicked < max(visible_times):
        raise ValueError('Run was not clicked during the packaged inspection')
    waiting = (max(visible_times) - clicked) / 1e9
    user_wait = duration('ack_start', 'ack_end') if matching('ack_start') else 0
    saved = Path(matching('saved')[0]['workbook'])
    elapsed = duration('drop', 'excel_end')
    return {'first_result_s': (min(visible_times) - drop) / 1e9, 'inspection_s': (max(visible_times) - drop) / 1e9,
            'run_clicked_s': (clicked - drop) / 1e9, 'waiting_s': waiting, 'user_wait_s': user_wait,
            'allocation_s': duration('allocation_start', 'allocation_end'),
            'reference_discounts_s': duration('discounts_start', 'discounts_end'),
            'excel_save_s': duration('excel_start', 'excel_end'), 'elapsed_s': elapsed,
            'processing_s': elapsed - user_wait, 'saved_workbook': str(saved), 'workbook_sha256': sha256(saved),
            'catalogs': observations}


def validate_catalog_rows(observed, evidence):
    if 'digital_financial_pairs' in evidence:
        validate_financial_source_evidence(observed, evidence)
        return
    expected = evidence['verified_rows']
    unresolved = evidence['unresolved_rows']
    if not expected and not unresolved:
        raise ValueError('Catalog has no verified source evidence')
    actual = observed['verified_rows']
    keys = ('source_id', 'page', 'name', 'price', 'discount')
    for rows in (actual, expected):
        if len({row['source_id'] for row in rows}) != len(rows):
            raise ValueError('Duplicate row source identity')
    actual_rows = {tuple(row[key] for key in keys) for row in actual}
    expected_rows = {tuple(row[key] for key in keys) for row in expected}
    if actual_rows != expected_rows or observed['accepted_rows'] != len(actual_rows):
        raise ValueError('Accepted rows differ from verified source evidence')
    observed_unresolved = set(observed['unresolved_source_ids'])
    if observed_unresolved != set(unresolved) or observed['unresolved_rows'] != len(observed_unresolved):
        raise ValueError('Unresolved rows differ from verified source evidence')
    if any(not isinstance(reason, str) or not reason.strip() for reason in unresolved.values()):
        raise ValueError('Each unresolved source identity requires an explanation')
    if observed['status'] != evidence['status']:
        raise ValueError('Catalog review status differs from verified source evidence')


def validate_financial_source_evidence(observed, evidence):
    """Check source-backed financial pairs and visually transcribed name anchors."""
    def numeric_pair(price, percent):
        return round(float(price), 6), round(float(percent), 6)

    digits = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹أإآةىی', '01234567890123456789اااهيي')

    def name_key(name):
        text = unicodedata.normalize('NFKC', name).translate(digits).replace('ـ', '').casefold()
        return ''.join(char for char in text if char.isalnum())

    actual = observed['observed_rows']
    unresolved = observed['unresolved']
    if observed['accepted_rows'] != len(actual) or observed['unresolved_rows'] != len(unresolved):
        raise ValueError('Catalog evidence does not account for every recorded row')
    if unresolved and observed['status'] not in {'partial', 'failed'}:
        raise ValueError('Catalog status does not reflect unresolved rows')
    if not evidence['anchors'] or not evidence['digital_financial_pairs']:
        raise ValueError('Catalog is missing financial positions or transcribed name anchors')

    accepted = Counter(numeric_pair(row['base_price'], 100 * row['discount_rate'])
                       for row in actual if row.get('discount_rate') is not None)
    source_rows = [(page['page'], row) for page in evidence['digital_financial_pairs']
                   for group in page['groups'] for row in group['paired_numeric_cells']]
    expected = Counter(numeric_pair(row['price'], row['discount_percent']) for _, row in source_rows)
    missing = expected - accepted

    def contains(container, position):
        x = (position[0] + position[2]) / 2
        y = (position[1] + position[3]) / 2
        return container[0] <= x <= container[2] and container[1] <= y <= container[3]

    accounted = set()
    for page, row in source_rows:
        pair = numeric_pair(row['price'], row['discount_percent'])
        if not missing[pair]:
            continue
        for issue in unresolved:
            box = issue.get('bbox')
            reason = issue.get('rejection_reason', '')
            identity = issue['source_id']
            if (identity not in accounted and issue.get('page_number') == page and box and reason
                    and contains(box, row['price_bbox']) and contains(box, row['discount_bbox'])):
                missing[pair] -= 1
                accounted.add(identity)
                break
    if any(missing.values()):
        raise ValueError(f'{sum(missing.values())} verified financial pairs are missing without a source-linked Review issue')

    observed_anchors = {(name_key(row['item_name']), *numeric_pair(row['base_price'], 100 * row['discount_rate']))
                        for row in actual if row.get('discount_rate') is not None}
    for anchor in evidence['anchors']:
        key = (name_key(anchor['printed_name']), *numeric_pair(anchor['price'], anchor['discount_percent']))
        if key not in observed_anchors:
            raise ValueError(f'Verified source name or financial fields differ on page {anchor["page"]}, row {anchor["printed_row"]}')


def batch(args):
    """Validate events exported by the packaged workflow and write its benchmark record."""
    manifest = read_json(args.inputs)
    catalogs = manifest['catalogs']
    hashes = {checked_hash(entry, args.inputs.parent) for entry in catalogs}
    if len(hashes) != 4 or len(catalogs) != 4:
        raise ValueError('Expected four different PDF catalogs')
    hashes.add(checked_hash(manifest['order'], args.inputs.parent))
    record = read_json(args.events)
    if record['executable_sha256'] != sha256(args.exe) or set(record['input_sha256']) != hashes:
        raise ValueError('Packaged evidence does not match the executable and input manifest')
    evidence = {entry['sha256']: entry for entry in catalogs}
    groups = {}
    source_discrepancies = []
    for entry in catalogs:
        if not entry.get('verified_rows') and not entry.get('unresolved_rows') and not entry.get('digital_financial_pairs'):
            raise ValueError('Source manifest requires verified rows or explained unresolved rows for each catalog')
    for trial in record['trials']:
        timings = ('first_result_s', 'inspection_s', 'waiting_s', 'allocation_s',
                   'reference_discounts_s', 'excel_save_s', 'user_wait_s', 'elapsed_s', 'processing_s')
        if not all(finite_number(trial.get(key)) for key in timings):
            raise ValueError('Missing or invalid packaged workflow timings')
        if abs(trial['elapsed_s'] - trial['user_wait_s'] - trial['processing_s']) > 0.05:
            raise ValueError('Elapsed, user waiting and processing timings disagree')
        if not 0 <= trial['run_clicked_s'] < trial['inspection_s'] <= trial['elapsed_s']:
            raise ValueError('Run was not clicked during inspection')
        workbook = (args.events.parent / trial['saved_workbook']).resolve()
        if trial['exit_code'] != 0 or workbook.suffix.lower() != '.xlsx' or sha256(workbook) != trial['workbook_sha256']:
            raise ValueError('Packaged workflow did not produce a verified workbook')
        observations = trial['catalogs']
        if len(observations) != 4 or {row['sha256'] for row in observations} != evidence.keys():
            raise ValueError('Expected one observation for each catalog in every trial')
        for row in observations:
            for key in ('parse_starts', 'worker_starts', 'ocr_calls'):
                if type(row[key]) is not int or row[key] < (1 if key == 'parse_starts' else 0):
                    raise ValueError(f'Invalid catalog counter: {key}')
            try:
                validate_catalog_rows(row, evidence[row['sha256']])
            except ValueError as exc:
                if not args.baseline:
                    raise
                source_discrepancies.append({'sha256': row['sha256'], 'trial': trial['launch'], 'reason': str(exc)})
        if trial['launch'] not in ('first', 'subsequent'):
            raise ValueError('Unknown packaged launch/cache classification')
        groups.setdefault(trial['launch'], []).append(trial)
    if set(groups) != {'first', 'subsequent'}:
        raise ValueError('First-launch and subsequent packaged trials are required')
    record['medians'] = {label: {key: statistics.median(trial[key] for trial in trials)
                                 for key in ('inspection_s', 'processing_s')}
                         for label, trials in groups.items()}
    record['source_evidence_sha256'] = sha256(args.inputs)
    record['source_checked'] = True
    record['source_verified'] = not source_discrepancies
    record['source_discrepancies'] = source_discrepancies
    write_json(args.out, record)


def collect_ocr(args):
    """Aggregate matched backend trials and explicit Review events exported by a benchmark run."""
    record = read_json(args.events)
    strips = record['strip_trials']
    if len(strips) < 2 or record.get('cache_disabled') is not True:
        raise ValueError('Paired uncached OCR strip trials are required')
    for sample in strips:
        if sample['dpi'] != 180 or sample['row_count'] != 7 or not sample['transform_sha256']:
            raise ValueError('Strip trials require matching transformations of seven rows at 180 DPI')
        for backend in ('native', 'powershell'):
            trial = sample[backend]
            if (trial['input_sha256'] != sample['input_sha256'] or trial['verified'] is not True
                    or trial['exit_code'] != 0 or not finite_number(trial['elapsed_s'])):
                raise ValueError(f'Invalid matched strip trial for {backend}')
    for backend in ('native', 'powershell'):
        samples = sorted(sample[backend]['elapsed_s'] for sample in strips)
        record.setdefault(backend, {}).update(sample_count=len(samples), p50_s=statistics.median(samples),
                                               p95_s=samples[math.ceil(len(samples) * 0.95) - 1])
    record['matched_inputs'] = True
    write_json(args.out, record)


def execute_strip_backend(args):
    """Isolate the OCR backend so the parent can enforce a process-tree deadline."""
    sys.path.insert(0, str(args.root.resolve()))
    import numpy as np
    from PIL import Image

    strip_paths = [Path(path) for path in read_json(args.images)]
    if args.backend == 'native':
        from src.native_ocr.win_context_ocr import ContextWindowOCR

        engine = ContextWindowOCR()
        started = time.perf_counter()
        if not engine.is_available():
            raise RuntimeError('Native OCR worker did not become available')
        ready = time.perf_counter() - started

        def recognize(image):
            response = engine.recognize_image(image, upscale=False, padding=0)
            if response.get('status') != 'ok':
                raise RuntimeError(f'Native OCR failed: {response.get("error")}')
            return response['lines']
    else:
        from src import ocr_engine

        ocr_engine.ContextWindowOCR = None
        engine = ocr_engine.ArabicOCREngine()
        started = time.perf_counter()
        worker = ocr_engine._get_or_create_windows_worker()
        if worker is None:
            raise RuntimeError('PowerShell OCR worker did not become available')
        ready = time.perf_counter() - started

        def recognize(image):
            with ocr_engine._OCR_CACHE_LOCK:
                ocr_engine._OCR_CACHE.clear()
            boxes = engine._extract_windows_ocr(image)
            if worker.poll() is not None or ocr_engine._WORKER_PROC is not worker:
                raise RuntimeError('PowerShell worker was replaced or fell back during the trial')
            return boxes

    trials = []
    for path in strip_paths:
        with Image.open(path) as png:
            pixels = np.array(png.convert('RGB'))
        started = time.perf_counter()
        result = recognize(pixels)
        elapsed = time.perf_counter() - started
        trials.append({'input_sha256': sha256(path), 'elapsed_s': elapsed,
                       'text': ' '.join(str(line['text']) for line in result)})
    write_json(args.out, {'ready_s': ready, 'trials': trials})


def run_ocr_strips(args):
    import pymupdf
    import unicodedata

    root = args.root.resolve()
    directory = args.directory.resolve()
    directory.mkdir(parents=True)
    specification = read_json(args.strips)
    strip_paths = []
    trials = []
    for index, strip in enumerate(specification['strips']):
        checked_hash(strip['pdf'], args.strips.parent)
        if strip['row_count'] != 7 or not strip['expected_tokens']:
            raise ValueError('Each strip must identify seven rows and independently verified text tokens')
        path = directory / f'{index + 1}.png'
        with pymupdf.open(args.strips.parent / strip['pdf']['path']) as pdf:
            page = pdf[strip['page'] - 1]
            clip = pymupdf.Rect(strip['bbox'])
            if clip.is_empty or not page.rect.contains(clip):
                raise ValueError(f'Invalid source strip bounds: {strip["bbox"]}')
            page.get_pixmap(dpi=180, clip=clip, alpha=False, colorspace=pymupdf.csRGB).save(path)
        strip_paths.append(str(path))
        trials.append({'input_sha256': sha256(path), 'dpi': 180, 'row_count': 7,
                       'transform_sha256': hashlib.sha256(b'PyMuPDF RGB 180dpi without scaling or padding').hexdigest(),
                       'expected_tokens': strip['expected_tokens']})
    image_list = directory / 'images.json'
    write_json(image_list, strip_paths)

    digits = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫', '01234567890123456789.')

    def normalized(text):
        return set(re.findall(r'\d+(?:\.\d+)?|[^\W\d_]+', unicodedata.normalize('NFKC', text).translate(digits)))

    record = {'strip_trials': trials, 'cache_disabled': True, 'windows': platform.platform(),
              'python': sys.version, 'language_configuration': specification['language_configuration'],
              'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True, timeout=10).strip(),
              'source_evidence_sha256': sha256(args.strips), 'executable_sha256': sha256(Path(sys.executable))}
    for backend in ('native', 'powershell'):
        output = directory / f'{backend}.json'
        command = [sys.executable, str(Path(__file__).resolve()), 'strip-backend', '--backend', backend,
                   '--root', str(root), '--images', str(image_list), '--out', str(output)]
        with launched(command, root, directory / backend) as (child, started, remember_tree):
            while child.poll() is None:
                remember_tree()
                if time.perf_counter() - started >= args.timeout:
                    raise TimeoutError(f'{backend} strip benchmark timed out')
                time.sleep(0.05)
            exit_code = child.returncode
        if exit_code:
            raise RuntimeError(f'{backend} strip benchmark exited with {exit_code}; see {directory / backend}')
        result = read_json(output)
        record[backend] = {'ready_s': result['ready_s']}
        for trial, observed in zip(trials, result['trials'], strict=True):
            tokens = normalized(observed['text'])
            verified = all(normalized(expected) <= tokens for expected in trial['expected_tokens'])
            trial[backend] = dict(observed, exit_code=exit_code, verified=verified)
        write_json(args.out, record)


def compare_evidence(base, candidate, ocr, before, after):
    def bounded(record, key, bound):
        value = record.get(key)
        return finite_number(value) and finite_number(bound) and value <= bound

    def app_budget(key, ratio):
        if (base.get('error') or candidate.get('error') or not base.get('input_sha256')
                or base.get('input_sha256') != candidate.get('input_sha256')):
            return False
        if any(len(record.get('trials', [])) < 5 for record in (base, candidate)):
            return False
        for label in ('first', 'subsequent'):
            reference = base.get('medians', {}).get(label, {}).get(key)
            current = candidate.get('medians', {}).get(label, {})
            if not finite_number(reference) or not bounded(current, key, reference * ratio):
                return False
        return True

    def ocr_review():
        review = ocr.get('review', {})
        for mode in ('source', 'frozen'):
            for temperature in ('cold', 'warm'):
                result = review.get(mode, {}).get(temperature, {})
                if result.get('comparable') is not True or not bounded(result, 'candidate_s', result.get('baseline_s')):
                    return False
        return True

    def packaged_improvement():
        if not before.get('source_evidence_sha256') or before.get('source_evidence_sha256') != after.get('source_evidence_sha256'):
            return False
        if before.get('source_checked') is not True or after.get('source_verified') is not True:
            return False
        for label in ('first', 'subsequent'):
            for key in ('inspection_s', 'processing_s'):
                old = before.get('medians', {}).get(label, {}).get(key)
                new = after.get('medians', {}).get(label, {}).get(key)
                if not finite_number(old) or not finite_number(new) or new >= old:
                    return False
        return True

    checks = candidate.get('checks', {})
    trials = after.get('trials', [])
    observed_catalogs = [row for trial in trials for row in trial.get('catalogs', [])]
    native = ocr.get('native', {})
    powershell = ocr.get('powershell', {})
    required_automatic = {'startup', 'digital_import', 'scanned_import', 'refresh',
                          'corrections_reload', 'procurement_fallback', 'open_review'}
    automatic = checks.get('automatic_ocr_calls', {})
    orphans = checks.get('orphan_workers', {})
    if not isinstance(automatic, dict):
        automatic = {}
    if not isinstance(orphans, dict):
        orphans = {}
    valid_scanned_timing = all(finite_number(candidate.get('medians', {}).get(label, {}).get('scanned_import_s'))
                               for label in ('first', 'subsequent'))
    faster = finite_number(native.get('p50_s')) and native['p50_s'] > 0 and bounded(native, 'p50_s', powershell.get('p50_s'))
    return {
        'B1': app_budget('startup_s', 1.10),
        'B2': app_budget('private_bytes', 1.10),
        'B3': app_budget('digital_import_s', 1.05),
        'B4': ocr_review(),
        'B5': bounded(native, 'ready_s', 1.5),
        'B6': bounded(native, 'p50_s', 0.250) and bounded(native, 'p95_s', 0.600),
        'B7': bool(faster and ocr.get('matched_inputs') is True and powershell['p50_s'] >= 3 * native['p50_s']),
        'B8': bounded(checks, 'tk_stall_s', 0.050),
        'B9': bounded(checks, 'installer_bytes', 150 * 1024 * 1024),
        'B10': bounded(checks, 'bundle_bytes', 480 * 1024 * 1024),
        'B11': bounded(checks, 'failed_start_session_s', 5),
        'B12': all(type(orphans.get(mode)) is int and orphans[mode] == 0 for mode in ('normal', 'os_exit')),
        'B13': bool(observed_catalogs and all(row.get('ocr_calls') == 0 and row.get('worker_starts') == 0
                                             for row in observed_catalogs) and valid_scanned_timing
                    and required_automatic <= automatic.keys()
                    and all(type(automatic[key]) is int and automatic[key] == 0 for key in required_automatic)),
        'B14': bool(observed_catalogs and all(row.get('parse_starts') == 1 for row in observed_catalogs)
                    and checks.get('inspection_failure_clears_waiting') is True
                    and checks.get('stale_inspection_rejected') is True),
        'B15': packaged_improvement(),
    }


def compare(args):
    evidence = []
    for path in (args.base, args.candidate, args.ocr, args.batch_before, args.batch_after):
        try:
            record = read_json(path)
            evidence.append(record if isinstance(record, dict) else {})
        except (OSError, ValueError) as exc:
            print(f'{path}: {exc}', file=sys.stderr)
            evidence.append({})
    gates = compare_evidence(*evidence)
    for key, passed in gates.items():
        print(f'{key} {"PASS" if passed else "FAIL (budget or evidence)"}')
    return 0 if all(gates.values()) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    source = commands.add_parser('app', help='Capture source-mode startup and catalog trials')
    source.add_argument('--root', type=Path, required=True)
    source.add_argument('--out', type=Path, required=True)
    source.add_argument('--logs', type=Path, default=Path('scratch/v272-baseline/logs'))
    source.add_argument('--trials', type=int, default=5)
    source.add_argument('--timeout', type=float, default=180)
    source.add_argument('--ocr-policy', choices=('automatic', 'explicit-only'), default='automatic')
    source.set_defaults(run=app)
    packaged = commands.add_parser('batch', help='Validate recorded packaged-workflow evidence')
    for name in ('exe', 'inputs', 'events', 'out'):
        packaged.add_argument(f'--{name}', type=Path, required=True)
    packaged.add_argument('--baseline', action='store_true', help='Record existing source discrepancies for the WIP baseline')
    packaged.set_defaults(run=batch)
    trial = commands.add_parser('run-packaged-trial', help='Run a benchmark-enabled frozen application once')
    for name in ('exe', 'inputs', 'directory'):
        trial.add_argument(f'--{name}', type=Path, required=True)
    trial.add_argument('--timeout', type=float, default=600)
    trial.set_defaults(run=run_packaged_trial)
    ocr = commands.add_parser('ocr', help='Aggregate matched backend and explicit Review OCR events')
    ocr.add_argument('--events', type=Path, required=True)
    ocr.add_argument('--out', type=Path, required=True)
    ocr.set_defaults(run=collect_ocr)
    strips = commands.add_parser('run-ocr-strips', help='Measure both Windows OCR backends on the same rendered strips')
    for name in ('root', 'strips', 'directory', 'out'):
        strips.add_argument(f'--{name}', type=Path, required=True)
    strips.add_argument('--timeout', type=float, default=120)
    strips.set_defaults(run=run_ocr_strips)
    backend = commands.add_parser('strip-backend', help=argparse.SUPPRESS)
    for name in ('root', 'images', 'out'):
        backend.add_argument(f'--{name}', type=Path, required=True)
    backend.add_argument('--backend', choices=('native', 'powershell'), required=True)
    backend.set_defaults(run=execute_strip_backend)
    comparison = commands.add_parser('compare', help='Evaluate all fifteen release gates')
    comparison.add_argument('base', type=Path)
    comparison.add_argument('candidate', type=Path)
    for name in ('ocr', 'batch-before', 'batch-after'):
        comparison.add_argument(f'--{name}', type=Path, required=True)
    comparison.set_defaults(run=compare)
    args = parser.parse_args()
    if getattr(args, 'trials', 1) < 1 or getattr(args, 'timeout', 1) <= 0:
        parser.error('Trials and timeout must be positive')
    try:
        return args.run(args)
    except (KeyError, OSError, RuntimeError, ValueError, psutil.Error) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    sys.exit(main())
