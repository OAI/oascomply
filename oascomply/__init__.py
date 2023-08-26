"""
:mod:`oascomply` package initialization

Resources with no clear point of first use for initialization
are initialized here.
"""
import os
import sys
import pathlib
import logging
import coloredlog
import jschon
import jschon.catalog
from jschon.catalog import _2020_12
from oascomply.oassource import DirectMapSource
from oascomply.resource import OASResourceManager, URI, OAS_SCHEMA_INFO
from oascomply.oas3dialect import (
    # TODO: sort out vs oascomply.patch
    OAS30_SCHEMA,
    OAS30_SCHEMA_PATH,
    OAS31_SCHEMA,
    OAS31_SCHEMA_PATH,
    OAS31_EXTENSION_METASCHEMA,
    OAS31_DIALECT_METASCHEMA,
    initialize_oas30_dialect,
    initialize_oas31_dialect,
)
from oascomply.schemaparse import (
    initialize_oas_specification_schemas,
)
from oascomply.patch import (
    PATCHED_OAS30_SCHEMA_DIR,
    PATCHED_OAS31_SCHEMA_PATH,
    PATCHED_OAS31_DIALECT_PATH,
    PATCHED_OAS31_META_PATH,
)

__all__ = [
    'catalog'
]

_oascomply_logger = logging.getLogger('oascomply')
_log_formatter = logging.Formatter(
    '%(asctime)s %(filename)s:%(lineno)d [%(levelname)s] %(message)s',
)
_log_handler = (
    coloredlog.ConsoleHandler(stream=sys.stderr)
    if sys.stderr.isatty() or os.getenv('OASCOMPLY_COLOR') == '1'
    else logging.StreamHandler()
)
_log_handler.setFormatter(_log_formatter)
_oascomply_logger.addHandler(_log_handler)

catalog = jschon.create_catalog(
    '2020-12',
    name='oascomply',
    resolve_references=False,
)
"""The default shared ``jschon``-derived resource loader and cache"""


catalog.add_uri_source(
    jschon.URI(
        'https://spec.openapis.org/compliance/schemas/dialect/2023-06/'
    ),
    jschon.catalog.LocalSource(
        (
            pathlib.Path(__file__) / '..' / '..' / 'schemas' / 'dialect'
        ).resolve(),
        suffix='.json',
    ),
)
catalog.add_uri_source(
    jschon.URI(
        'https://spec.openapis.org/compliance/schemas/meta/2023-06/'
    ),
    jschon.catalog.LocalSource(
        (
            pathlib.Path(__file__) / '..' / '..' / 'schemas' / 'meta'
        ).resolve(),
        suffix='.json',
    ),
)
catalog.add_uri_source(
    jschon.URI(
        'https://spec.openapis.org/oas/v3.0/dialect/',
    ),
    jschon.catalog.LocalSource(PATCHED_OAS30_SCHEMA_DIR, suffix='.json'),
)

OASResourceManager.update_direct_mapping(
    catalog,
    {
        URI(OAS30_SCHEMA): OAS30_SCHEMA_PATH,
        URI(OAS31_SCHEMA): OAS31_SCHEMA_PATH,
        URI(OAS31_DIALECT_METASCHEMA): PATCHED_OAS31_DIALECT_PATH,
        URI(OAS31_EXTENSION_METASCHEMA): PATCHED_OAS31_META_PATH,
    },
)

_2020_12.initialize(catalog)
initialize_oas30_dialect(catalog)
initialize_oas31_dialect(catalog)
initialize_oas_specification_schemas(catalog)
