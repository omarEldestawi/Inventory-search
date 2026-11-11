import pytest

from src.box_ocr_parser import normalize_numeric, parse_box_words


def word(text, x, y=0):
    return {'text': text, 'bbox': (x, y, x + 8, y + 10)}


def test_verified_columns_normalize_arabic_and_persian_numbers():
    result = parse_box_words([word('١٥٠٫۲۵', 0), word('٢٠٪', 40)],
                             column_roles={'price': (0, 0, 15, 10), 'discount': (35, 0, 55, 10)})
    assert result.price == 150.25
    assert result.discount_percent == 20
    assert result.provenance['price']['evidence'] == 'verified column'
    assert normalize_numeric('۱٬۲۰۰٫۵') == '1,200.5'


@pytest.mark.parametrize('values', [('12.50', '25'), ('245', '18'), ('150.75',), ('12', '25')])
def test_unlabeled_numbers_do_not_suggest_financial_fields(values):
    result = parse_box_words([word(value, 10 * index) for index, value in enumerate(values)])
    assert result.price is None
    assert result.discount_percent is None
    assert result.name is None


def test_percent_does_not_imply_other_numbers_are_prices():
    result = parse_box_words([word('Panadol', 0), word('500', 12), word('25%', 24)])
    assert result.name == 'Panadol 500'
    assert result.price is None
    assert result.discount_percent == 25


def test_verified_price_cell_joins_only_punctuated_close_fragments():
    roles = {'price': (0, 0, 40, 10)}
    assert parse_box_words([word('125', 0), word('.50', 10)], column_roles=roles).price == 125.50
    assert parse_box_words([word('12', 0), word('25', 10)], column_roles=roles).price is None
    assert parse_box_words([word('125', 0), word('.50', 30)], column_roles=roles).price is None


def test_conflicting_evidence_never_selects_a_financial_value():
    assert parse_box_words([word('25%', 0), word('26%', 20)]).discount_percent is None
    result = parse_box_words([word('price', 0), word('25%', 10)])
    assert result.price is None and result.discount_percent is None
    assert parse_box_words([word('price:', 0), word('12.50', 10)]).price == 12.50


def test_multiple_rows_and_empty_output_remain_unresolved():
    assert parse_box_words([]).notes == ('No text detected',)
    result = parse_box_words([word('25%', 0), word('26%', 0, 20)])
    assert result.discount_percent is None
    assert result.notes == ('Select a single row',)


def test_rtl_name_retains_detached_strength_and_excludes_verified_pack_cell():
    result = parse_box_words([word('ابيدون', 60), word('١٢٥', 50), word('مل', 40), word('٢٤', 0)],
                             column_roles={'pack': (0, 0, 10, 10), 'name': (40, 0, 70, 10)},
                             sort_bidi=lambda words: list(reversed(words)))
    assert result.name == 'ابيدون ١٢٥ مل'
    assert result.price is None
