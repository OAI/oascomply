from __future__ import annotations

import re
import logging
import pathlib
from os import PathLike
from dataclasses import dataclass
from typing import Hashable, Mapping, Optional, Sequence, Tuple, Type, Union
import json

import jschon
import jschon.utils
from jschon.catalog import Catalog, Source

from oascomply import resourceid as rid
from oascomply.oas30dialect import (
    OAS30_DIALECT_METASCHEMA, OAS30_SUBSET_VOCAB, OAS30_EXTENSION_VOCAB,
)
from oascomply.oasjson import OASJSON, OASJSONSchema
from oascomply.oassource import OASSource

__all__ = [
    'OASCatalog',
    'OASJSON',
    'OASJSONSchema',
    'initialize_oas_specification_schemas',
]

logger = logging.getLogger(__name__)


class OASCatalog(Catalog):

    # TODO: Using JSONSchema allows requests that resolve to JSON, but
    #       using OASJSONSchema somehow does not?????
    _json_schema_cls = jschon.JSONSchema # OASJSONSchema

    def __init__(self, *args, **kwargs):
        self._uri_url_map = {}
        self._uri_sourcemap_map = {}
        super().__init__(*args, **kwargs)

    def add_uri_source(
        self,
        base_uri: Optional[jschon.URI],
        source: Source,
    ) -> None:
        # This "base URI" is really treated as a prefix, which
        # is why a value of '' works at all.
        uri_prefix = rid.Iri('' if base_uri is None else str(base_uri))
        if isinstance(source, OASSource):
            source.set_uri_prefix(uri_prefix)
        super().add_uri_source(uri_prefix, source)

    def _get_with_url_and_sourcemap(
        self,
        uri,
        *,
        cacheid,
        metaschema_uri,
        cls,
    ):
        base_uri = uri.copy(fragment=None)
        document_cached = isinstance(
            self._schema_cache[oasversion].get(base_uri),
            resourceclass,
        )

        # TODO: get_schema() is a misnomer but exact method naming
        #       scheme TBD in the next jschon version.
        oas = self.get_schema(
            uri,
            cacheid=cacheid,
            metaschema_uri=metaschema_uri,
            cls=resourceclass,
        )

        if not document_cached:
            url = OASSource.get_url(base_uri)
            oas.document_root.url = url
            oas.document_root.source_map = OASSource.get_sourcemap(base_uri)

        return oas

    def get_oas(
        self,
        oasversion: str,
        uri: jschon.URI,
        *,
        resourceclass: Type[jschon.JSON] = None,
        oas_schema_uri: rid.Iri = None,
    ):
        if resourceclass is None:
            resourceclass = OASJSON

        if oas_schema_uri is None:
            oas_schema_uri = self.get_oas_schema_uri(oasversion)

        return self._get_with_url_and_sourcemap(
            uri,
            cacheid=oasversion,
            metaschema_uri=oas_schema_uri,
            resourceclass=cls,
        )

    def get_oas_schema(
            self,
            oasversion: str,
            uri: jschon.URI,
            *,
            metaschema_uri: jschon.URI = None,
            resourceclass: Type[jschon.JSON] = None,
    ) -> jschon.JSONSchema:
        if resourceclass is None:
            resourceclass = OASJSONSchema

        if metaschema_uri is None:
            metaschema_uri = self.get_metaschema_uri(oasversion)

        return self._get_with_url_and_sourcemap(
            uri,
            cacheid=oasversion,
            metaschema_uri=oas_schema_uri,
            resourceclass=cls,
        )


def initialize_oas_specification_schemas(catalog: OASCatalog):
    for oasversion, oasinfo in OASJSON.SUPPORTED_OAS_VERSIONS.items():
        # As a metaschema, the OAS schema behaves like the corresponding
        # dialect metaschema as that is what it should use by default when
        # it encounters a Schema Object.  Objects betweenthe document root
        # and the Schema Objects are not JSONSchema subclasses and are
        # therefore treated like regular instance validation.
        catalog._json_schema_cls._metaschema_cls(
            catalog,
            jschon.utils.json_loads(
                oasinfo['schema']['path'].read_text(encoding='utf-8'),
            ),
            catalog.get_vocabulary(catalog._json_schema_cls._uri_cls('https://json-schema.org/draft/2020-12/vocab/core')),
            catalog.get_vocabulary(catalog._json_schema_cls._uri_cls(OAS30_SUBSET_VOCAB)),
            catalog.get_vocabulary(catalog._json_schema_cls._uri_cls(OAS30_EXTENSION_VOCAB)),
        )
