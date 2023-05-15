from itertools import chain
import jschon
import pytest

from oascomply.ptrtemplates import (
    JSONPointerTemplate,
    InvalidJSONPointerTemplateError,
    JSONPointerTemplateEvaluationError,
    RelativeJSONPointerTemplate,
    InvalidRelativeJSONPointerTemplateError,
    RelativeJSONPointerTemplateEvaluationError,
)


@pytest.mark.parametrize('unescaped,escaped', (
    ('~', '~0'),
    ('/', '~1'),
    ('{', '~2'),
    ('}', '~3'),
    ('~/{}', '~0~1~2~3'),
))
def test_escape(unescaped, escaped):
    import sys
    sys.stderr.write(f"{unescaped!r} {escaped!r}")
    assert JSONPointerTemplate.escape(unescaped) == escaped


@pytest.mark.parametrize('escaped,unescaped', (
    ('~0', '~'),
    ('~1', '/'),
    ('~2', '{'),
    ('~3', '}'),
    ('~0~1~2~3', '~/{}'),
))
def test_unescape(escaped, unescaped):
    import sys
    sys.stderr.write(f"{escaped!r} {unescaped!r}")
    assert JSONPointerTemplate.unescape(escaped) == unescaped


@pytest.mark.parametrize('template_str,components', (
    ('', [jschon.JSONPointer()]),
    ('/', [jschon.JSONPointer('/')]),
    ('/foo', [jschon.JSONPointer('/foo')]),
    ('/~2escaped~3/~1~0', [jschon.JSONPointer('/{escaped}/~1~0')]),
    ('/{varname}', ['varname']),
    ('/{varname}#', ['varname', True]),
    ('/foo/bar/{a}/{b}/qux/quux', [
        jschon.JSONPointer('/foo/bar'),
        'a',
        'b',
        jschon.JSONPointer('/qux/quux'),
    ]),
    ('/bar#', [jschon.JSONPointer('/bar#')]),
))
def test_constructor(template_str, components):
    jpt = JSONPointerTemplate(template_str)
    assert jpt._components == components


@pytest.mark.parametrize('template_str', (
    '0',  # relative JSON pointer
    '1#', # relative JSON Pointer
    '/{no~1escapes}',
    '/{toosoon}#/etc',
    '/{trailing}characters',
    '/leading{characters}',
))
def test_constructor_errors(template_str):
    with pytest.raises(
        InvalidJSONPointerTemplateError,
        match='not a valid JSONPointerTemplate',
    ):
        JSONPointerTemplate(template_str)


TEST_DOCUMENT = jschon.JSON({
    'a': ['b', 'c', 'd'],
    'e': {
        'f': ['g', 'h'],
        'i': ['j', 'k'],
    },
})


@pytest.mark.parametrize('template,output', (
    (
        JSONPointerTemplate(''),
        [(jschon.JSONPointer(''), TEST_DOCUMENT, {}, None)],
    ), (
        JSONPointerTemplate('/a/0'),
        [(jschon.JSONPointer('/a/0'), TEST_DOCUMENT['a'][0], {}, None)],
    ), (
        JSONPointerTemplate('/e/{key}'),
        [
            (
                jschon.JSONPointer(f'/e/{key}'),
                TEST_DOCUMENT['e'][key],
                {'key': key},
                None,
            ) for key in TEST_DOCUMENT['e']
        ],
    ), (
        JSONPointerTemplate('/e/{key}#'),
        [
            (
                jschon.JSONPointer(f'/e/{key}'),
                TEST_DOCUMENT['e'][key],
                {'key': key},
                key,
            ) for key in TEST_DOCUMENT['e']
        ],
    ), (
        JSONPointerTemplate('/e/{key1}/{index}'),
        list(chain.from_iterable([
            [
                (
                    jschon.JSONPointer(f'/e/{key1}/{index}'),
                    TEST_DOCUMENT['e'][key1][index],
                    {'key1': key1, 'index': index},
                    None,
                ) for index in range(len(TEST_DOCUMENT['e'][key1]))
            ] for key1 in TEST_DOCUMENT['e'].keys()
        ])),
    ), (
        JSONPointerTemplate('/nope/{whatever}'),
        [],
    )
))
def test_evaluation(template, output):
    actual = list(
        template.evaluate(TEST_DOCUMENT)
    )
    assert actual == output


@pytest.mark.parametrize('template,match,require', (
    ('/nope', 'not found in document', True),
    ('/a/0/{scalar}', 'Cannot match template variable', False),
    ('/a/0/{scalar}', 'Cannot match template variable', True),
))
def test_evaluation_errors(template, match, require):
    jpt = JSONPointerTemplate(template)
    with pytest.raises(JSONPointerTemplateEvaluationError, match=match):
        list(jpt.evaluate(TEST_DOCUMENT, require_match=require))


@pytest.mark.parametrize('template_str,relptr,jptemplate', (
    ('1+3#', jschon.RelativeJSONPointer('1+3#'), None),
    ('0/foo', jschon.RelativeJSONPointer('0'), JSONPointerTemplate('/foo')),
    (
        '1/{bar}#',
        jschon.RelativeJSONPointer('1'),
        JSONPointerTemplate('/{bar}#'),
    ),
))
def test_rel_constructor(template_str, relptr, jptemplate):
    rjpt = RelativeJSONPointerTemplate(template_str)
    assert rjpt._relptr == relptr
    assert rjpt._jptemplate == jptemplate


@pytest.mark.parametrize('template_str,match', (
    ('0#/foo', "Can't use '#'"),
    ('stuff/nonsense', 'not a valid RelativeJSONPointerTemplate'),
    ('0/{bar}#/foo', 'not a valid RelativeJSONPointerTemplate'),
))
def test_rel_constructor_errors(template_str, match):
    with pytest.raises(InvalidRelativeJSONPointerTemplateError, match=match):
        RelativeJSONPointerTemplate(template_str)


@pytest.mark.parametrize('template,start,output', (
    (
        RelativeJSONPointerTemplate('0+1'),
        jschon.JSONPointer('/a/1').evaluate(TEST_DOCUMENT),
        [(jschon.RelativeJSONPointer('0+1'), TEST_DOCUMENT['a'][2], {}, None)],
    ), (
        RelativeJSONPointerTemplate('1#'),
        jschon.JSONPointer('/e/f').evaluate(TEST_DOCUMENT),
        [(jschon.RelativeJSONPointer('1#'), TEST_DOCUMENT['e'], {}, 'e')],
    ), (
        RelativeJSONPointerTemplate('0/{var}'),
        jschon.JSONPointer('/e/i').evaluate(TEST_DOCUMENT),
        [
            (
                jschon.RelativeJSONPointer('0/0'),
                TEST_DOCUMENT['e']['i'][0],
                {'var': 0},
                None,
            ),
            (
                jschon.RelativeJSONPointer('0/1'),
                TEST_DOCUMENT['e']['i'][1],
                {'var': 1},
                None,
            ),
        ],
    ), (
        RelativeJSONPointerTemplate('0/nope/{whatever}'),
        TEST_DOCUMENT,
        [],
    )
))
def test_rel_evaluation(template, start, output):
    actual = list(template.evaluate(start))
    assert actual == output

@pytest.mark.parametrize('template,start,match,require', (
    (
        RelativeJSONPointerTemplate('1/{whatever}'),
        TEST_DOCUMENT,
        'Could not evaluate origin',
        False,
    ), (
        RelativeJSONPointerTemplate('0/x'),
        TEST_DOCUMENT,
        r'Path .* not found .* \(after applying',
        True,
    )
))
def test_rel_evaluation_errors(template, start, match, require):
    with pytest.raises(RelativeJSONPointerTemplateEvaluationError, match=match):
        list(template.evaluate(start, require_match=require))
