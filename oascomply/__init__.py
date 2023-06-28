"""
:mod:`oascomply` package initialization

Resources with no clear point of first use for initialization
are initialized here.
"""
import pathlib
import jschon
import jschon.catalog
from oascomply.oas30dialect import initialize_oas30_dialect

__all__ = [
    'schema_catalog'
]

schema_catalog = jschon.create_catalog('2020-12')
"""The default shared ``jschon`` schema loader and cache"""

schema_catalog.add_uri_source(
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
schema_catalog.add_uri_source(
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
schema_catalog.add_uri_source(
    jschon.URI(
        'https://spec.openapis.org/oas/v3.0/dialect/',
    ),
    jschon.catalog.LocalSource(
        (
            pathlib.Path(__file__) / '..' / '..' / 'schemas' / 'oas' / 'v3.0'
        ).resolve(),
        suffix='.json',
    ),
)

initialize_oas30_dialect(schema_catalog)
