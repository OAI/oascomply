import sys
import logging
from pathlib import Path

import jschon

import pytest

from oascomply.resource import (
    URI,
    ThingToURI,
    PathToURI,
    URLToURI,
)


from . import (
    BASE_URI,
    FOO_YAML_URI,
    FOO_URI,
    DIR_URI,
    OTHER_URI,
    FOO_JSON_PATH,
    FOO_PATH,
    FOO_JSON_PATH_URL,
    FOO_PATH_URL,
    CURRENT_DIR,
    CURRENT_DIR_URL,
)


@pytest.mark.parametrize('args,thing,uri', (
    (['about:blank'], 'about:blank', jschon.URI('about:blank')),
    ([['about:blank']], 'about:blank', jschon.URI('about:blank')),
    ([str(FOO_YAML_URI), ['.json']], str(FOO_YAML_URI), FOO_YAML_URI),
    ([[str(FOO_YAML_URI)], ['.yaml']], str(FOO_YAML_URI), FOO_URI),
    ([str(BASE_URI), (), True], str(BASE_URI), BASE_URI),
    (
        [['foo', str(OTHER_URI)]],
        'foo',
        OTHER_URI,
    ),
    (
        [['foo.yaml', str(OTHER_URI)], ['.yaml']],
        'foo.yaml',
        OTHER_URI,
    ),
    (
        [['foo.yaml', str(FOO_YAML_URI)], ['.yaml']],
        'foo.yaml',
        FOO_YAML_URI,
    ),
    (
        [['foo', str(BASE_URI)], (), True],
        'foo',
        BASE_URI,
    ),
))
def test_thing_to_uri(args, thing, uri):
    t = ThingToURI(*args)
    assert t.thing == thing
    assert t.uri == uri
    assert t.auto_uri == (isinstance(args[0], str) or len(args[0]) == 1)


@pytest.mark.parametrize('args,error', (
    ([()], "Expected 1 or 2 values"),
    ([str(FOO_YAML_URI), (), True], "must have a path ending in '/'"),
    (['https://ex.org/?query', (), True], "not include a query or fragment"),
    (['https://ex.org/#frag', (), True], "not include a query or fragment"),
    (['foo'], 'cannot be relative'),
))
def test_thing_to_uri_errors(args, error, caplog):
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError, match=error):
            ThingToURI(*args)
    assert error in caplog.text


def test_thing_to_uri_set_uri():
    t = ThingToURI(['about:blank', str(FOO_YAML_URI)])
    t.set_uri(str(FOO_URI))
    assert t.uri == FOO_URI


@pytest.mark.parametrize('args', (
    ['about:blank'],
    [[str(OTHER_URI), str(BASE_URI)], ['.json'], True],
))
def test_thing_to_uri_repr(args):
    t = ThingToURI(*args)
    repr_args = [
        [args[0]] if isinstance(args[0], str) else args[0],
        args[1] if len(args) > 1 else (),
        args[2] if len(args) > 2 else False,
    ]
    assert repr(t) == \
        f'ThingToURI({repr_args[0]}, {repr_args[1]}, {repr_args[2]})'


@pytest.mark.parametrize('left,right,equal', (
    (
        ThingToURI(['about:blank', str(FOO_URI)]),
        ThingToURI(['about:blank', str(FOO_URI)]),
        True,
    ),
    (
        ThingToURI([str(OTHER_URI), str(FOO_URI)]),
        ThingToURI(['about:blank', str(FOO_URI)]),
        False,
    ),
    (
        ThingToURI(['about:blank', str(OTHER_URI)]),
        ThingToURI(['about:blank', str(FOO_URI)]),
        False,
    ),
))
def test_thing_to_uri_eq(left, right, equal):
    assert (left == right) is equal


@pytest.mark.parametrize('args,path,uri', (
    (['foo.json', ['.yaml']], FOO_JSON_PATH, FOO_JSON_PATH_URL),
    (['foo.json', ['.json']], FOO_JSON_PATH, FOO_PATH_URL),
    (['./', ['.json'], True], CURRENT_DIR, CURRENT_DIR_URL),
))
def test_path_to_uri(args, path, uri):
    p = PathToURI(*args)
    assert p.path == path
    assert p.uri == uri
    assert p.thing == p.path


def test_path_to_uri_str():
    assert (
        str(PathToURI(
            [str(FOO_JSON_PATH), str(FOO_PATH_URL)],
            ['.json'],
        ))
        ==
        f'(path: {FOO_JSON_PATH}, uri: <{FOO_PATH_URL}>)'
    )


def test_prefix_requires_dir(caplog):
    error = 'must be a directory'
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError, match=error):
            PathToURI('ldkjfsdfjlsfjdjfsdf', [], True)
    assert error in caplog.text


@pytest.mark.parametrize('args,url,uri', (
    ([str(FOO_YAML_URI), ['.json']], FOO_YAML_URI, FOO_YAML_URI),
    ([[str(BASE_URI), str(DIR_URI)], [], True], BASE_URI, DIR_URI),
))
def test_url_to_uri(args, url, uri):
    u = URLToURI(*args)
    assert u.url == url
    assert u.uri == uri
    assert u.thing == u.url


def test_no_rel_url(caplog):
    error = 'cannot be relative'
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError, match=error):
            URLToURI(['foo', 'about:blank'])
    assert error in caplog.text


def test_url_must_be_prefix(caplog):
    error = "must have a path ending in '/'"
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError, match=error):
            URLToURI(['about:blank', str(BASE_URI)], [], True)
    assert error in caplog.text
