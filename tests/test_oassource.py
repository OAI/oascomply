from dataclasses import FrozenInstanceError
import pathlib
from typing import Tuple
from unittest import mock

import pytest

from oascomply.oassource import (
    ParsedContent,
    ResourceLoader,
    FileLoader,
    HttpLoader,
    ContentParser,
    OASSource,
    MultiSuffixSource,
    FileMultiSuffixSource,
    HttpMultiSuffixSource,
    DirectMapSource,
)
from oascomply.resource import URI


def test_parsed_content():
    v = {'foo': 'bar'}
    url = 'about:blank'
    sourcemap = {}

    pc = ParsedContent(v, url, sourcemap)
    assert pc.value is v
    assert pc.url is url
    assert pc.sourcemap is sourcemap

    
    # Test frozen-ness
    with pytest.raises(FrozenInstanceError):
        pc.value = {}
    with pytest.raises(FrozenInstanceError):
        pc.url = 'https://example.com'
    with pytest.raises(FrozenInstanceError):
        pc.sourcemap = None


@pytest.mark.parametrize('info,parser,create_sm', (
    (None, '_unknown_parse', None),
    ('', '_unknown_parse', True),
    ('.json', '_json_parse', False),
    ('.yaml', '_yaml_parse', True),
    ('.yml', '_yaml_parse', False),
))
def test_parser(info, parser, create_sm):
    cp = ContentParser(())
    assert cp.get_parser(info) == getattr(cp, parser)

    path = pathlib.Path('foo' + ('' if info is None else info)).resolve()

    with mock.patch.object(cp, parser) as mock_parser:
        if create_sm is not None:
            cp.parse(path, info, create_sm)
            assert mock_parser.mock_calls == [mock.call(path, create_sm)]
        else:
            cp.parse(path, info)
            assert mock_parser.mock_calls == [mock.call(path, False)]


def test_direct_map_loaders():
    assert DirectMapSource.get_loaders() == (FileLoader, HttpLoader)


@pytest.mark.parametrize('mapping', (
    {
        URI('https://ex.com/foo'): URI('https://ex.com/urls/foo.yaml'),
        URI('https://ex.com/bar'): URI('https://ex.com/urls/bar.json'),
        URI('https://ex.com/baz'): URI('https://ex.com/urls/baz'),
    },
    {
        URI('https://example.com/foo'): pathlib.Path('path/foo.yaml').resolve(),
        URI('https://example.com/bar'): pathlib.Path('path/bar.json').resolve(),
        URI('https://example.com/baz'): pathlib.Path('path/baz').resolve(),
    },
))
def test_direct_map(mapping):
    dm = DirectMapSource(mapping)
    assert dm._map == mapping
    assert dm._map is not mapping

    for uri, location in mapping.items():
        with mock.patch.object(
            dm._parser, 'parse', autospec=True
        ) as mock_parse:
            dm.resolve_resource(str(uri))
            last = str(location).split('/')[-1]
            suffix = last[last.rindex('.'):] if '.' in last else ''
            assert mock_parse.mock_calls == [mock.call(location, suffix)]
