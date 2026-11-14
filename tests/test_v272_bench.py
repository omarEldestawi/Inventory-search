import pytest

from scripts.bench_v272 import compare_evidence, summarize_trace, validate_catalog_rows


def test_missing_evidence_fails_every_gate():
    gates = compare_evidence({}, {}, {}, {}, {})
    assert set(gates) == {f'B{number}' for number in range(1, 16)}
    assert not any(gates.values())


def test_complete_evidence_passes_and_regressions_fail_independently():
    timing = {'startup_s': 1, 'private_bytes': 1, 'digital_import_s': 1, 'scanned_import_s': 1}
    app = {'input_sha256': {'digital': 'sample'}, 'trials': [{}] * 5,
           'medians': {'first': timing, 'subsequent': timing}}
    checks = {'tk_stall_s': 0.04, 'installer_bytes': 1, 'bundle_bytes': 1,
              'failed_start_session_s': 4, 'orphan_workers': {'normal': 0, 'os_exit': 0},
              'automatic_ocr_calls': dict.fromkeys(('startup', 'digital_import', 'scanned_import', 'refresh',
                                                    'corrections_reload', 'procurement_fallback', 'open_review'), 0),
              'inspection_failure_clears_waiting': True, 'stale_inspection_rejected': True}
    candidate = dict(app, checks=checks)
    review = dict(comparable=True, candidate_s=1, baseline_s=2)
    ocr = {'native': {'ready_s': 1, 'p50_s': 0.2, 'p95_s': 0.5}, 'powershell': {'p50_s': 0.7},
           'review': {mode: {'cold': review, 'warm': review} for mode in ('source', 'frozen')},
           'matched_inputs': True}

    def batch(seconds):
        median = {'inspection_s': seconds, 'processing_s': seconds}
        return {'source_evidence_sha256': 'same', 'source_checked': True, 'source_verified': True,
                'medians': {'first': median, 'subsequent': median}, 'trials': [
                    {'catalogs': [{'parse_starts': 1, 'ocr_calls': 0, 'worker_starts': 0}]}]}

    before, after = batch(2), batch(1)
    assert all(compare_evidence(app, candidate, ocr, before, after).values())
    checks['tk_stall_s'] = 0.06
    after['trials'][0]['catalogs'][0]['parse_starts'] = 2
    del ocr['review']['source']['cold']
    gates = compare_evidence(app, candidate, ocr, before, after)
    assert {key for key, passed in gates.items() if not passed} == {'B4', 'B8', 'B14'}


def test_packaged_trace_counts_duplicate_parses_and_excludes_acknowledgment(tmp_path):
    path = str(tmp_path / 'catalog.pdf')
    workbook = tmp_path / 'report.xlsx'
    workbook.write_bytes(b'workbook fixture')

    def event(name, second, **payload):
        return {'name': name, 'time_ns': second * 10 ** 9, 'pid': 1, 'thread': 1, **payload}

    row = {'source_id': 'p1_t0_g0_r1', 'item_name': 'Sample', 'base_price': 12.50, 'discount_rate': 0.25}
    events = [
        event('drop', 0), event('parse_start', 1, path=path), event('run_clicked', 2, in_progress=True),
        event('ocr_call', 3), event('parse_end', 4, path=path, rows=[row], unresolved=[], status='complete'),
        event('parse_start', 5, path=path), event('parse_end', 6, path=path, rows=[row], unresolved=[], status='complete'),
        event('inspection_visible', 7, path=path), event('ack_start', 8), event('ack_end', 10),
        event('allocation_start', 11), event('allocation_end', 12), event('discounts_start', 12),
        event('discounts_end', 14), event('excel_start', 14), event('excel_end', 17),
        event('saved', 18, workbook=str(workbook)),
    ]
    trial = summarize_trace(events, [{'path': path, 'sha256': 'sample'}], tmp_path)
    assert trial['catalogs'][0]['parse_starts'] == 2
    assert trial['catalogs'][0]['ocr_calls'] == 1
    assert trial['catalogs'][0]['verified_rows'][0]['price'] == 12.50
    assert trial['user_wait_s'] == 2
    assert trial['waiting_s'] == 5
    assert trial['processing_s'] == 15
    assert trial['excel_save_s'] == 3


def test_source_audit_requires_a_located_review_issue_for_missing_financial_pair():
    anchor = {'page': 1, 'printed_row': 1, 'printed_name': 'دواء ١٢ مل', 'price': 12.50, 'discount_percent': 25}
    accepted_pair = {'price': 12.50, 'discount_percent': 25, 'price_bbox': [0, 0, 10, 10], 'discount_bbox': [10, 0, 20, 10]}
    quarantined_pair = {'price': 53, 'discount_percent': 86, 'price_bbox': [0, 11, 10, 20], 'discount_bbox': [10, 11, 20, 20]}
    evidence = {'anchors': [anchor], 'digital_financial_pairs': [
        {'page': 1, 'groups': [{'paired_numeric_cells': [accepted_pair, quarantined_pair]}]}]}
    issue = {'source_id': 'p1_t0_r2', 'page_number': 1, 'bbox': [0, 11, 20, 20], 'rejection_reason': 'invalid_discount_0.86'}
    result = {'accepted_rows': 1, 'unresolved_rows': 1, 'status': 'partial', 'unresolved': [issue],
              'observed_rows': [{'item_name': 'دواء 12 مل', 'base_price': 12.50, 'discount_rate': 0.25}]}
    validate_catalog_rows(result, evidence)
    issue['page_number'] = 2
    with pytest.raises(ValueError, match='missing without a source-linked Review issue'):
        validate_catalog_rows(result, evidence)


def test_b4_requires_both_native_and_fallback_when_backend_nested():
    timing = {'startup_s': 1, 'private_bytes': 1, 'digital_import_s': 1, 'scanned_import_s': 1}
    app = {'input_sha256': {'digital': 'sample'}, 'trials': [{}] * 5,
           'medians': {'first': timing, 'subsequent': timing}}
    checks = {'tk_stall_s': 0.04, 'installer_bytes': 1, 'bundle_bytes': 1,
              'failed_start_session_s': 4, 'orphan_workers': {'normal': 0, 'os_exit': 0},
              'automatic_ocr_calls': dict.fromkeys(('startup', 'digital_import', 'scanned_import', 'refresh',
                                                    'corrections_reload', 'procurement_fallback', 'open_review'), 0),
              'inspection_failure_clears_waiting': True, 'stale_inspection_rejected': True}
    candidate = dict(app, checks=checks)
    review = dict(comparable=True, candidate_s=1, baseline_s=2)
    per_mode = {mode: {'cold': review, 'warm': review} for mode in ('source', 'frozen')}
    ocr = {'native': {'ready_s': 1, 'p50_s': 0.2, 'p95_s': 0.5}, 'powershell': {'p50_s': 0.7},
           'review': {'native': per_mode, 'fallback': {mode: {'cold': dict(review), 'warm': dict(review)} for mode in ('source', 'frozen')}},
           'matched_inputs': True}
    median = {'inspection_s': 2, 'processing_s': 2}
    before = {'source_evidence_sha256': 'same', 'source_checked': True, 'source_verified': True,
              'medians': {'first': median, 'subsequent': median}, 'trials': [
                  {'catalogs': [{'parse_starts': 1, 'ocr_calls': 0, 'worker_starts': 0}]}]}
    after = {'source_evidence_sha256': 'same', 'source_checked': True, 'source_verified': True,
             'medians': {'first': {'inspection_s': 1, 'processing_s': 1}, 'subsequent': {'inspection_s': 1, 'processing_s': 1}},
             'trials': [{'catalogs': [{'parse_starts': 1, 'ocr_calls': 0, 'worker_starts': 0}]}]}
    assert compare_evidence(app, candidate, ocr, before, after)['B4'] is True
    del ocr['review']['fallback']['frozen']['warm']
    assert compare_evidence(app, candidate, ocr, before, after)['B4'] is False
