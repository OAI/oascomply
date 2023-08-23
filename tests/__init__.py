import logging
from pathlib import Path

import jschon


logging.getLogger('oascomply').setLevel(logging.DEBUG)


BASE_URI = jschon.URI('https://example.com/')
FOO_YAML_URI = BASE_URI.copy(path='/foo.yaml')
FOO_URI = BASE_URI.copy(path='/foo')
DIR_URI = jschon.URI('https://test.com/bar/')
OTHER_URI = jschon.URI('tag:example.com,2023:bar')


def normalize_file_url(url_str: str, append_slash=False) -> str:
    # URI libraries are inconsistent about this.  oascomply
    # has settled on file:/ over file:/// due to limitations of
    # the rfc3986 library used by jschon.uri.URI.
    u = jschon.URI(url_str).copy(authority=None)
    return str(
        u.copy(path=u.path + '/') if append_slash
        else u
    )


FOO_JSON_PATH = Path('foo.json').resolve()
FOO_PATH = Path('foo').resolve()
FOO_JSON_PATH_URL = normalize_file_url(FOO_JSON_PATH.as_uri())
FOO_PATH_URL = normalize_file_url(FOO_PATH.as_uri())

CURRENT_DIR = Path('.').resolve()
CURRENT_DIR_URL = normalize_file_url(CURRENT_DIR.as_uri(), append_slash=True)
