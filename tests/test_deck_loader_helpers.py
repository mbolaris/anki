from pathlib import Path

from anki_viewer.deck_loader import _sanitize_media_filename, _build_field_map, _normalize_template_key


def test_sanitize_edge_cases():
    assert _sanitize_media_filename('') == 'media'
    # Path('..').name == '..' - ensure we preserve the name rather than failing
    assert _sanitize_media_filename('..') == '..'
    assert _sanitize_media_filename('weird/na me.jpg') == 'na_me.jpg'


def test_build_field_map():
    fields = ['a', 'b', 'c']
    names = ['One', 'Two']
    mapping = _build_field_map(fields, names)
    assert mapping['One'] == 'a'
    assert mapping['Two'] == 'b'
    assert mapping['Field3'] == 'c'


def test_normalize_template_key():
    assert _normalize_template_key('  Front :: something ') == 'something'
    assert _normalize_template_key('') == ''
    assert _normalize_template_key('Field') == 'Field'


def test_render_cloze_and_media_inline():
    from anki_viewer.deck_loader import _render_cloze, _inline_media

    # Cloze rendering: hint when not revealed
    html = '{{c1::Paris::city}}'
    out = _render_cloze(html, reveal=False, active_index=1)
    assert 'class="cloze hint"' in out or 'cloze hint' in out

    # Cloze reveal shows content wrapped in mark
    out_revealed = _render_cloze(html, reveal=True, active_index=1)
    assert '<mark' in out_revealed and 'Paris' in out_revealed

    # Inline media with quoted and unquoted sources
    media_map = {'img.png': 'img.png', 'photo': 'photo.png'}
    html_q = '<img src="img.png">'
    assert _inline_media(html_q, media_map, '/media') == '<img src="/media/img.png">'
    html_uq = '<img src=photo>'
    assert '/media/photo.png' in _inline_media(html_uq, media_map, '/media')


def test_render_anki_template_sections():
    from anki_viewer.deck_loader import _render_anki_template

    tmpl = 'Hello {{Field1}}'
    assert _render_anki_template(tmpl, {'Field1': 'World'}) == 'Hello World'

    # Section rendering: only render inner when field is truthy
    tmpl2 = 'Start {{#Field1}}YES{{/Field1}} End'
    assert _render_anki_template(tmpl2, {'Field1': ''}) == 'Start  End'
    assert _render_anki_template(tmpl2, {'Field1': 'x'}) == 'Start YES End'
