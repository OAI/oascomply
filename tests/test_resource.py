import sys
import logging
from pathlib import Path

import jschon

import pytest

from oascomply.resource import (
    OASNodeBase,
    OASNode,
    OASContainer,
    OASDocument,
    OASFormat,
    OASFragment,
    OASResourceManager,
    URI,
    ThingToURI,
    PathToURI,
    URLToURI,
    OAS_SCHEMA_INFO,
)
from oascomply.oassource import (
    DirectMapSource, FileMultiSuffixSource, HttpMultiSuffixSource,
)
from oascomply.cli import DEFAULT_SUFFIXES


from . import (
    normalize_file_url,
    BASE_URI,
    FOO_YAML_URI,
    FOO_URI,
    DIR_URI,
    OTHER_URI,
    FOO_JSON_PATH,
    FOO_PATH,
    FOO_JSON_PATH_URL,
    FOO_PATH_URL,
    BAR_YAML_PATH,
    BAR_PATH,
    BAR_YAML_PATH_URL,
    BAR_PATH_URL,
    CURRENT_DIR,
    CURRENT_DIR_URL,
)


# Local filesystem paths where the files actually live
A_DIR = (Path(__file__).parent / 'local-data' / 'a').resolve()
B_DIR = (Path(__file__).parent / 'local-data' / 'b').resolve()
A_PATH = (A_DIR / 'openapi.yaml').resolve()
B_PATH = (B_DIR / 'openapi.json').resolve()
B_SCHEMA_PATH = (B_PATH.parent / 'schema.json').resolve()
A_JUNK_PATH = (A_DIR / 'junk.yaml').resolve()

# URL representations of the local filesytem paths
A_DIR_URL = normalize_file_url(A_DIR.as_uri(), append_slash=True)
B_DIR_URL = normalize_file_url(B_DIR.as_uri(), append_slash=True)
A_PATH_URL = URI(A_PATH.as_uri())
B_PATH_URL = URI(B_PATH.as_uri())
B_SCHEMA_PATH_URL = URI(B_SCHEMA_PATH.as_uri())
A_JUNK_PATH_URL = URI(A_JUNK_PATH.as_uri())

# file URIs without the suffix
A_DIR_URI = A_DIR_URL
B_DIR_URI = B_DIR_URL
A_PATH_URI = URI(A_PATH.with_suffix('').as_uri())
B_PATH_URI = URI(B_PATH.with_suffix('').as_uri())
B_SCHEMA_PATH_URI = URI(B_SCHEMA_PATH.with_suffix('').as_uri())
A_JUNK_PATH_URI = URI(A_JUNK_PATH.with_suffix('').as_uri())

# HTTP URI representations (no suffixes, generic domain without host)
AB_PREFIX_URI = URI('https://example.com/apis/')
A_PREFIX_URI = URI('https://example.com/apis/a/')
A_URI = URI('https://example.com/apis/a/openapi')
B_PREFIX_URI = URI('https://example.com/apis/b/')
B_URI = URI('https://example.com/apis/b/openapi')
B_SCHEMA_URI = URI('https://example.com/apis/b/schema')
A_JUNK_URI = URI('https://example.com/apis/a/junk')

# HTTP URL representations (suffixes vary to test with content types)
AB_PREFIX_URL = URI('https://server1.example.com/somewhere/')
A_PREFIX_URL = URI('https://server1.example.com/somewhere/a/')
A_URL = URI('https://server1.example.com/somewhere/a/openapi')
A_CONTENT_TYPE = 'application/openapi+yaml'
B_PREFIX_URL = URI('https://server1.example.com/somwewhere/b/')
B_URL = URI('https://server1.example.com/somwewhere/b/openapi.json')
B_CONTENT_TYPE = 'application/openapi+json'
B_SCHEMA_URL = URI('https://server1.example.com/somewhere/b/schema')
B_SCHEMA_CONTENT_TYPE = 'application/schema+json'
A_JUNK_URL = URI('https://sever1.example.com/somewhere/a/junk')
A_JUNK_CONTENT_TYPE = 'application/yaml'

@pytest.fixture
def catalog():
    return jschon.create_catalog('2020-12', name='test')


@pytest.fixture
def manager(catalog):
    return OASResourceManager(
        catalog,
        directories=[
            PathToURI([str(A_DIR), str(A_PREFIX_URI)], uri_is_prefix=True),
            PathToURI([str(B_DIR), str(B_PREFIX_URI)], uri_is_prefix=True),
        ],
        dir_suffixes=['.json', '.yaml'],
    )


def test_update_direct_mapping(catalog):
    uri1 = URI('https://example.com/foo')
    uri2 = URI('about:blank')
    path1 = Path('foo.json').resolve()
    path2 = Path('bar.yaml').resolve()
    path3 = Path('baz').resolve()

    mapping = {uri1: path1, uri2: path2}

    OASResourceManager.update_direct_mapping(catalog, mapping)

    dm = OASResourceManager._direct_sources[catalog]
    assert isinstance(dm, DirectMapSource), type(dm).__name__
    assert dm._map == mapping

    OASResourceManager.update_direct_mapping(catalog, {uri1: path3})

    updated_map = {uri1: path3, uri2: path2}
    assert OASResourceManager._direct_sources[catalog]._map == updated_map


@pytest.mark.parametrize('base,prefix', (
    (None, ''),
    (URI('https://example.com/'), 'https://example.com/'),
))
def test_add_uri_source(base, prefix, catalog):
    dm = DirectMapSource({})
    OASResourceManager.add_uri_source(catalog, base, dm)

    assert dm._uri_prefix == prefix
    assert catalog._uri_sources[prefix] is dm
    assert OASResourceManager._url_maps[catalog] is dm._uri_url_map
    assert OASResourceManager._sourcemap_maps[catalog] is dm._uri_sourcemap_map


@pytest.mark.parametrize('kwargs,sources', (
    # Just files (-f) and sometimes suffix stripping
    # Note that the actual CLI can't set -x differently per -f
    (
        {
            'files': [
                # -f file -x .json
                PathToURI(str(FOO_JSON_PATH), ('.json',)),
                # -f file uri
                PathToURI(
                    [str(BAR_YAML_PATH), str(OTHER_URI)],
                    DEFAULT_SUFFIXES,
                ),
                # -f file -x
                PathToURI(str(B_SCHEMA_PATH), ()),
            ],
        },
        {
            '': {
                'cls': DirectMapSource,
                'attrs': {
                    '_map': {
                        FOO_PATH_URL: FOO_JSON_PATH,
                        OTHER_URI: BAR_YAML_PATH,
                        B_SCHEMA_PATH_URL: B_SCHEMA_PATH,
                    },
                },
            },
        },
    ),
    # Just URLs (-u) and sometimes suffix stripping
    # Note that the actual CLI can't set -x differently per -u
    (
        {
            'urls': [
                # -u url uri
                URLToURI([str(A_URL), str(A_URI)], DEFAULT_SUFFIXES),
                # -u url -x json
                URLToURI(str(B_URL), ('.json',)),
                # -u url -x
                URLToURI(str(B_SCHEMA_URL), ()),
            ],
        },
        {
            '': {
                'cls': DirectMapSource,
                'attrs': {
                    '_map': {
                        A_URI: A_URL,
                        # Produces suffixed-sripped B_URL, not B_URI
                        URI(str(B_URL)[:-len('.json')]): B_URL,
                        B_SCHEMA_URL: B_SCHEMA_URL,
                    },
                },
            },
        },
    ),
    # -d only
    (
        {
            'directories': [
                PathToURI(str(A_DIR), uri_is_prefix=True),
                PathToURI([str(B_DIR), str(BASE_URI)], uri_is_prefix=True),
            ],
        },
        {
            str(A_DIR_URI): {
                'cls': FileMultiSuffixSource,
                'attrs': {
                    '_prefix': f'{A_DIR}/',
                    '_suffixes': (),
                },
            },
            str(BASE_URI): {
                'cls': FileMultiSuffixSource,
                'attrs': {
                    '_prefix': f'{B_DIR}/',
                    '_suffixes': (),
                },
            },
        },
    ),
    # -d and -D
    (
        {
            'directories': [
                PathToURI(str(A_DIR), uri_is_prefix=True),
                PathToURI([str(B_DIR), str(BASE_URI)], uri_is_prefix=True),
            ],
            'dir_suffixes': ['.json', '.yaml'],
        },
        {
            str(A_DIR_URI): {
                'cls': FileMultiSuffixSource,
                'attrs': {
                    '_prefix': f'{A_DIR}/',
                    '_suffixes': ['.json', '.yaml'],
                },
            },
            str(BASE_URI): {
                'cls': FileMultiSuffixSource,
                'attrs': {
                    '_prefix': f'{B_DIR}/',
                    '_suffixes': ['.json', '.yaml'],
                },
            },
        },
    ),
    # -p only
    (
        {
            'url_prefixes': [
                URLToURI(str(A_PREFIX_URL), uri_is_prefix=True),
                URLToURI(
                    [str(B_PREFIX_URL), str(BASE_URI)],
                    uri_is_prefix=True,
                ),
            ],
        },
        {
            # Auto-generated URI prefix is just the URL prefix
            str(A_PREFIX_URL): {
                'cls': HttpMultiSuffixSource,
                'attrs': {
                    '_prefix': str(A_PREFIX_URL),
                    '_suffixes': (),
                },
            },
            str(BASE_URI): {
                'cls': HttpMultiSuffixSource,
                'attrs': {
                    '_prefix': str(B_PREFIX_URL),
                    '_suffixes': (),
                },
            },
        },
    ),
    # -p and -P
    (
        {
            'url_prefixes': [
                URLToURI(str(A_PREFIX_URL), uri_is_prefix=True),
                URLToURI(
                    [str(B_PREFIX_URL), str(BASE_URI)],
                    uri_is_prefix=True,
                ),
            ],
            'url_suffixes': ['.json', '.yaml'],
        },
        {
            # Auto-generated URI prefix is just the URL prefix
            str(A_PREFIX_URL): {
                'cls': HttpMultiSuffixSource,
                'attrs': {
                    '_prefix': str(A_PREFIX_URL),
                    '_suffixes': ['.json', '.yaml'],
                },
            },
            str(BASE_URI): {
                'cls': HttpMultiSuffixSource,
                'attrs': {
                    '_prefix': str(B_PREFIX_URL),
                    '_suffixes': ['.json', '.yaml'],
                },
            },
        },
    ),
    # everything, everywhere, all at once (files version)
    (
        {
            'directories': [
                PathToURI([str(A_DIR), str(A_DIR_URI)], uri_is_prefix=True),
            ],
            'dir_suffixes': ['.yaml'],
            'files': [
                PathToURI(str(A_PATH), ['.json']),
                PathToURI(
                    [str(A_PATH.parent / 'x'), str(OTHER_URI)],
                    ['.json'],
                ),
                PathToURI(str(B_PATH), ['.json']),
            ],
        },
        {
            '': {
                'cls': DirectMapSource,
                'attrs': {
                    '_map': {
                        OTHER_URI: A_PATH.parent / 'x',
                        B_PATH_URI: B_PATH,
                    },
                },
            },
            str(A_DIR_URI): {
                'cls': FileMultiSuffixSource,
                'attrs': {
                    '_prefix': f'{A_DIR}/',
                    '_suffixes': ['.yaml'],
                },
            },
        }
    ),
    # everything, everywhere, all at once (HTTP version)
    (
        {
            'url_prefixes': [
                URLToURI(
                    [str(A_PREFIX_URL), str(A_PREFIX_URI)],
                    uri_is_prefix=True,
                ),
            ],
            'url_suffixes': ['.yaml'],
            'urls': [
                URLToURI(str(A_URL), ['.json']),
                URLToURI(
                    [str(URI('../x').resolve(A_URL)), str(OTHER_URI)],
                    ['.json'],
                ),
                URLToURI(str(B_URL), ['.json']),
            ],
        },
        {
            '': {
                'cls': DirectMapSource,
                'attrs': {
                    '_map': {
                        OTHER_URI: URI('../x').resolve(A_URL),
                        # Produces suffixed-sripped B_URL, not B_URI
                        URI(str(B_URL)[:-len('.json')]): B_URL,
                    },
                },
            },
            str(A_PREFIX_URI): {
                'cls': HttpMultiSuffixSource,
                'attrs': {
                    '_prefix': str(A_PREFIX_URL),
                    '_suffixes': ['.yaml'],
                },
            },
        }
    ),
))
def test_manager_init(kwargs, sources, catalog):
    rm = OASResourceManager(catalog, **kwargs)
    for prefix in sources:
        assert prefix in catalog._uri_sources

        s = catalog._uri_sources[prefix]
        assert isinstance(s, sources[prefix]['cls'])

        for attr, value in sources[prefix]['attrs'].items():
            assert getattr(s, attr) == value, f'{type(s).__name__}.{attr}'


def test_resource_loading(manager):
    apid = manager.get_oas(A_URI)
    assert isinstance(apid, OASDocument)
    assert apid.oasversion == '3.0'
    assert apid.url == A_PATH_URL
    assert apid.sourcemap is None
    assert apid['x-id'] == str(A_URI)

    assert apid.is_format_root()
    assert apid.format_root is apid
    assert apid.format_parent is None
    assert apid.parent_in_format is None

    assert apid.is_resource_root()
    assert apid.resource_root is apid
    assert apid.resource_parent is None
    assert apid.parent_in_resource is None

    assert apid.document_root is apid

    for key in apid:
        assert isinstance(apid[key], OASNode), "key '{key}'"
        assert apid[key].is_resource_root() is False
        assert apid[key].resource_root is apid
        assert apid[key].resource_parent == apid[key].parent
        assert apid[key].parent_in_resource == apid[key].parent
        assert apid[key].document_root is apid
        assert apid[key].pointer_uri == apid.uri.copy(fragment=f'/{key}')
        if key == 'info':
            for ikey in apid[key]:
                assert isinstance(apid[key][ikey], OASNode), "key '{key}'"


def test_oas_container(manager):
    p = manager.get_oas(A_JUNK_URI, oasversion='3.0', oastype='PathItem')
    assert isinstance(p, OASFragment)
    assert p.oasversion == '3.0'
    assert p.metadocument_uri == URI(
        OAS_SCHEMA_INFO['3.0']['schema']['uri'],
    ).copy(fragment=f'/$defs/PathItem')
