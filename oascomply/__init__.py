"""
:mod:`oascomply` package initialization

Resources with no clear point of first use for initialization
are initialized here.
"""
import pathlib
import jschon
import jschon.catalog
from jschon.catalog import _2020_12
from oascomply.oascatalog import (
        OASCatalog, initialize_oas_specification_schemas,
)
from oascomply.oassource import DirectMapSource
from oascomply.oas3dialect import (
    initialize_oas30_dialect,
    initialize_oas31_dialect,
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


catalog = OASCatalog('oascomply', resolve_references=False)
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
catalog.add_uri_source(
    None,
    DirectMapSource(
        {
            jschon.URI('https://spec.openapis.org/oas/3.1/schema/2022-10-07'):
                PATCHED_OAS31_SCHEMA_PATH,
            jschon.URI('https://spec.openapis.org/oas/3.1/dialect/strict'):
                PATCHED_OAS31_DIALECT_PATH,
            jschon.URI('https://spec.openapis.org/oas/3.1/meta/base'):
                PATCHED_OAS31_META_PATH,
        },
        suffixes=('.json',)
    ),
)


_2020_12.initialize(catalog)
initialize_oas30_dialect(catalog)
initialize_oas31_dialect(catalog)
initialize_oas_specification_schemas(catalog)
