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
from jschon.vocabulary import Metaschema

from oascomply import resourceid as rid
from oascomply.oas3dialect import (
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
    def __init__(self, *args, **kwargs):
        self._uri_url_map = {}
        self._uri_sourcemap_map = {}
        super().__init__(*args, **kwargs)

    def add_uri_source(
        self,
        base_uri: Optional[jschon.URI],
        source: Source,
    ) -> None:
        super().add_uri_source(base_uri, source)
        if isinstance(source, OASSource):
            # This "base URI" is really treated as a prefix, which
            # is why a value of '' works at all.
            uri_prefix = rid.IriReference('' if base_uri is None else str(base_uri))
            source.set_uri_prefix(uri_prefix)
            source.set_uri_url_map(self._uri_url_map)
            source.set_uri_sourcemap_map(self._uri_sourcemap_map)

    def _get_with_url_and_sourcemap(
        self,
        uri,
        *,
        oasversion,
        metadocument_uri,
        cls,
    ):
        base_uri = uri.copy(fragment=None)
        document_cached = isinstance(
            self._schema_cache.get(oasversion, {}).get(base_uri),
            cls,
        )

        oas = self.get_resource(
            uri,
            cacheid=oasversion,
            metadocument_uri=metadocument_uri,
            cls=cls,
        )

        if not document_cached:
            oas.document_root.url = self._uri_url_map[str(base_uri)]
            oas.document_root.source_map = self._uri_sourcemap_map[str(base_uri)]

        return oas

    def get_oas(
        self,
        uri: jschon.URI,
        oasversion: str,
        *,
        resourceclass: Type[jschon.JSON] = None,
        oas_schema_uri: rid.Iri = None,
    ):
        if resourceclass is None:
            resourceclass = OASJSON

        if oas_schema_uri is None:
            oas_schema_uri = OASJSON.get_schema_object_metaschema_uri(oasversion)

        return self._get_with_url_and_sourcemap(
            uri,
            oasversion=oasversion,
            metadocument_uri=oas_schema_uri,
            cls=resourceclass,
        )

    def get_oas_schema(
            self,
            oasversion: str,
            uri: jschon.URI,
            *,
            metadocument_uri: jschon.URI = None,
            resourceclass: Type[jschon.JSON] = None,
    ) -> jschon.JSONSchema:
        if resourceclass is None:
            resourceclass = OASJSONSchema

        if metadocument_uri is None:
            metadocument_uri = OASJSON.get_oas_metadocument_uri(oasversion)

        return self._get_with_url_and_sourcemap(
            uri,
            cacheid=oasversion,
            metadocument_uri=oas_schema_uri,
            resourceclass=cls,
        )


def initialize_oas_specification_schemas(catalog: OASCatalog):
    for oasversion, oasinfo in OASJSON.SUPPORTED_OAS_VERSIONS.items():
        # As a metaschema, the OAS schema behaves like the corresponding
        # dialect metaschema as that is what it should use by default when
        # it encounters a Schema Object.  Objects between the document root
        # and the Schema Objects are not JSONSchema subclasses and are
        # therefore treated like regular instance validation.
        Metaschema(
            catalog,
            jschon.utils.json_loads(
                oasinfo['schema']['path'].read_text(encoding='utf-8'),
            ),
            catalog.get_vocabulary(jschon.URI('https://json-schema.org/draft/2020-12/vocab/core')),
            catalog.get_vocabulary(jschon.URI(OAS30_SUBSET_VOCAB)),
            catalog.get_vocabulary(jschon.URI(OAS30_EXTENSION_VOCAB)),
        )
