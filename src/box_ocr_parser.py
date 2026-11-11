"""Attribute OCR words to fields using source geometry and explicit labels."""

from dataclasses import dataclass, field
import math
import re
import unicodedata


_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬٪', '01234567890123456789.,%')
_NUMBER = re.compile(r'(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?')
_LABELS = {'price': 'price', 'السعر': 'price', 'سعر': 'price',
           'discount': 'discount', 'الخصم': 'discount', 'خصم': 'discount'}
_ROLES = {'name', 'price', 'discount', 'quantity', 'pack', 'code'}


@dataclass(frozen=True)
class BoxParseResult:
    name: str | None = None
    price: float | None = None
    discount_percent: float | None = None
    notes: tuple[str, ...] = ()
    raw_text: str = ''
    provenance: dict = field(default_factory=dict)


@dataclass(frozen=True)
class _Word:
    text: str
    bbox: tuple[float, float, float, float]

    @property
    def center(self):
        return ((self.bbox[0] + self.bbox[2]) / 2, (self.bbox[1] + self.bbox[3]) / 2)


def normalize_numeric(text):
    """Normalize decimal, grouping and percent glyphs without joining digits across tokens."""
    text = unicodedata.normalize('NFKC', text).translate(_DIGITS)
    return ''.join(char for char in text if unicodedata.category(char) != 'Cf').strip()


def _number(text):
    normalized = normalize_numeric(text)
    percent = normalized.startswith('%') or normalized.endswith('%')
    if percent:
        normalized = (normalized[1:] if normalized.startswith('%') else normalized[:-1]).strip()
    if not _NUMBER.fullmatch(normalized):
        return None, percent
    value = float(normalized.replace(',', ''))
    return (value if math.isfinite(value) else None), percent


def _bbox(value):
    box = tuple(float(coord) for coord in value)
    if len(box) != 4 or not all(map(math.isfinite, box)) or box[0] >= box[2] or box[1] >= box[3]:
        raise ValueError('Invalid OCR bounding box')
    return box


def _close(left, right):
    return right.bbox[0] - left.bbox[2] <= min(left.bbox[3] - left.bbox[1], right.bbox[3] - right.bbox[1])


def parse_box_words(words, *, column_roles=None, sort_bidi=None):
    """Read one row with independently verified cell boxes in the same coordinate space."""
    words = [word for word in words if str(word.get('text', '')).strip()]
    raw_text = ' '.join(word['text'].strip() for word in words)
    if not words:
        return BoxParseResult(notes=('No text detected',))
    try:
        tokens = sorted((_Word(word['text'].strip(), _bbox(word['bbox'])) for word in words), key=lambda word: word.bbox[0])
        cells = {role: _bbox(box) for role, box in (column_roles or {}).items() if role in _ROLES}
    except (KeyError, TypeError, ValueError):
        return BoxParseResult(raw_text=raw_text, notes=('OCR geometry is missing or invalid',))

    top = max(word.bbox[1] for word in tokens)
    bottom = min(word.bbox[3] for word in tokens)
    if top >= bottom:
        return BoxParseResult(raw_text=raw_text, notes=('Select a single row',))

    def cell_roles(word):
        x, y = word.center
        return {role for role, box in cells.items() if box[0] <= x < box[2] and box[1] <= y < box[3]}

    labels = [_LABELS.get(unicodedata.normalize('NFKC', word.text).lower().rstrip(':：')) for word in tokens]
    suggestions = {'price': [], 'discount': []}
    conflicts = set()
    name = []
    notes = []
    index = 0
    while index < len(tokens):
        word = tokens[index]
        if labels[index]:
            index += 1
            continue
        roles = cell_roles(word)
        source = 'verified column' if roles else None
        adjacent_labels = {labels[neighbor] for neighbor in (index - 1, index + 1)
                           if 0 <= neighbor < len(tokens) and labels[neighbor]
                           and _close(tokens[min(index, neighbor)], tokens[max(index, neighbor)])}
        value, percent = _number(word.text)
        if adjacent_labels and (value is not None or percent):
            roles |= adjacent_labels
            source = source or 'explicit label'

        boxes = [word.bbox]
        if roles == {'price'} and cell_roles(word) == {'price'} and index + 1 < len(tokens):
            next_word = tokens[index + 1]
            fragment = normalize_numeric(next_word.text)
            if (re.fullmatch(r'[0-9]+', normalize_numeric(word.text)) and re.fullmatch(r'\.[0-9]+', fragment)
                    and cell_roles(next_word) == {'price'} and _close(word, next_word)):
                value, percent = _number(normalize_numeric(word.text) + fragment)
                boxes.append(next_word.bbox)
                index += 1
        if percent:
            roles.add('discount')
            source = source or 'percent marker'
        financial_roles = roles & suggestions.keys()
        if len(roles) > 1:
            conflicts.update(financial_roles)
        elif financial_roles:
            role = next(iter(financial_roles))
            valid = value is not None and (value > 0 if role == 'price' else 0 <= value <= 100)
            if valid:
                suggestions[role].append((value, {'evidence': source, 'boxes': boxes}))
            else:
                conflicts.add(role)
        elif roles == {'name'} or (not roles and 'name' not in cells):
            name.append(word)
        index += 1

    provenance = {}
    values = {}
    for role, candidates in suggestions.items():
        if role in conflicts or len(candidates) != 1:
            notes.append(f'{role.title()} requires verification')
            continue
        values[role], provenance[role] = candidates[0]
    item_name = None
    name_has_letters = any(unicodedata.category(char).startswith('L') for word in name for char in word.text)
    unassigned_numbers = [word for word in name if not cell_roles(word) and _number(word.text)[0] is not None]
    if name_has_letters and len(unassigned_numbers) > 1:
        notes.append('Select the name cell to avoid including numbers from other columns')
    elif name_has_letters:
        word_dicts = [{'text': word.text, 'bbox': word.bbox} for word in name]
        if sort_bidi is not None:
            word_dicts = sort_bidi(word_dicts)
        item_name = ' '.join(word['text'] for word in word_dicts)
        provenance['name'] = {'evidence': 'row text', 'boxes': [word.bbox for word in name]}
    return BoxParseResult(item_name, values.get('price'), values.get('discount'), tuple(notes), raw_text, provenance)
