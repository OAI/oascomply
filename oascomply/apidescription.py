import json
from collections import defaultdict
from typing import (
    Any, Iterator, Mapping, Optional, Sequence, Tuple, Type, Union
)
import logging
import os
import sys

import jschon
from jschon.catalog import Source
from jschon.jsonformat import JSONFormat
from jschon.vocabulary import Metaschema

import rdflib
from rdflib.namespace import RDF

import oascomply
from oascomply.oasgraph import OasGraph
from oascomply.schemaparse import (
    Annotation, SchemaParser, JsonSchemaParseError,
)
from oascomply.oassource import OASSource
from oascomply.oas3dialect import (
    OAS30_SCHEMA,
    OAS30_DIALECT_METASCHEMA,
    OAS31_SCHEMA,
    OAS31_DIALECT_METASCHEMA,
)

__all__ = [
    'ApiDescription',
    'OASResourceManager',
]

logger = logging.getLogger(__name__)


ANNOT_ORDER = (
    'oasType',
    'oasTypeGroup',
    'oasReferences',
    'oasChildren',
    'oasLiterals',
    'oasExtensible',
    'oasApiLinks',
    'oasDescriptionLinks',
    'oasExamples',
)


class OASJSONFormat(JSONFormat):
    _default_metadocument_cls = Metaschema

    def __init__(self, *args, catalog='oascomply', **kwargs):
        self.oasversion = '3.0'
        self.sourcemap = None
        self.url = None
        super().__init__(*args, catalog='oascomply', **kwargs)


class OASResourceManager:
    """
    Proxy for the jschon.Catalog, adding OAS-specific handling.

    This class manages the flow of extra information that
    :class:`jschon.catalog.Catalog` and :class:`jschon.catalog.Source` do not
    directly support.  This includes recording the URL from which a resource
    was loaded, as well as other metadata about its stored document form.
    """
    def __init__(self, catalog: jschon.Catalog):
        self._catalog = catalog
        self._uri_url_map = {}
        self._uri_sourcemap_map = {}

    def add_uri_source(
        self,
        base_uri: Optional[jschon.URI],
        source: Source,
    ) -> None:
        self._catalog.add_uri_source(base_uri, source)
        if isinstance(source, OASSource):
            # This "base URI" is really treated as a prefix, which
            # is why a value of '' works at all.
            uri_prefix = jschon.URI('' if base_uri is None else str(base_uri))
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
        r = self._catalog.get_resource(
            uri,
            cacheid=oasversion,
            metadocument_uri=metadocument_uri,
            cls=cls,
        )

        if r.document_root.url is None:
            r.document_root.url = self._uri_url_map[str(base_uri)]
            r.document_root.source_map = self._uri_sourcemap_map[str(base_uri)]

        return r

    def get_oas(
        self,
        uri: jschon.URI,
        oasversion: str,
        *,
        resourceclass: Type[jschon.JSON] = OASJSONFormat,
        oas_schema_uri: Optional[jschon.URI] = None,
    ):
        if oas_schema_uri is None:
            oas_schema_uri = {
                '3.0': OAS30_SCHEMA,
                '3.1': OAS31_SCHEMA,
            }[oasversion]

        oas_doc = self._get_with_url_and_sourcemap(
            uri,
            oasversion=oasversion,
            metadocument_uri=oas_schema_uri,
            cls=resourceclass,
        )
        return oas_doc


class ApiDescription:
    """
    Representation of a complete API description.

    The constructor arguments are used to load the primary API description
    resource.  This resource MUST contain an ``openapi`` field setting
    the version.  Currently, 3.0.x descriptions are supported, with 3.1.x
    support intended for a later version.

    Note that at most one of ``path`` or ``url`` can be passed.

    :param document: The primary OAS document data
    :param uri: The URI for the primary OAS document
    :param path: The local filesystem path of the OAS document
    :param url: The URL from which the primary OAS document was retrieved
    :param sourcemap: A data structure mapping JSON pointer to lines and columns
    :param test_mode: If true, ensures that output can be used for repeatable
        testing by removing environment-specific information such as file names
    """

    def __init__(
        self,
        document,
        *,
        resource_manager: OASResourceManager,
        test_mode: bool = False,
    ) -> None:

        # TODO: "entry" vs "primary"
        self._primary_resource = document
        self._manager = resource_manager
        self._test_mode = test_mode

        if 'openapi' not in document:
            raise ValueError(
                "Initial API description must include `openapi` field!"
                f"{path} <{uri}>"
            )
        if document.oasversion != '3.0':
            if document.oasversion == '3.1':
                raise NotImplementedError("OAS v3.1 support stil in progress")
            raise ValueError(f"OAS v{self._version} not supported!")

        if (
            document.uri.path and '/' in document.uri.path and
            not document.uri.path.endswith('/')
        ):
            # RDF serialization works better with a directory
            # as a base IRI, particularly for multi-document
            # API descriptions within a single directory.
            # Otherwise it fails to notice many opportunities to
            # shorten IRI-references.
            self._base_uri = document.uri.copy(
                path=document.uri.path[:document.uri.path.rindex('/') + 1]
            )
        else:
            self._base_uri = document.uri

        self._g = OasGraph(
            document.oasversion,
            test_mode=self._test_mode,
        )
        self._g.add_resource(document.url, document.uri)

        self._validated = []

    @property
    def oasversion(self) -> str:
        return self._primary_resource.oasversion

    @property
    def base_uri(self) -> jschon.URI:
        """
        The base URI for the overal API document set.

        This is used in some output serialization formats.
        """
        return self._base_uri

    @property
    def validated_resources(self) -> Tuple[jschon.URI]:
        """Read-only list of validated resource URIs, in validation order."""
        return tuple(self._validated)

    def validate(
        self,
        resource_uri=None,
        oastype='OpenAPI',
        validate_examples=True,
    ):
        sp = SchemaParser.get_parser({}, annotations=ANNOT_ORDER)
        errors = []

        # TODO: Probably don't need to track resource_uri separately
        if resource_uri is None:
            assert oastype == 'OpenAPI'
            resource_uri = self._primary_resource.uri
        elif isinstance(resource_uri, str):
            # TODO: IRI vs URI
            # TODO: Non-JSON Pointer fragments in 3.1
            resource_uri = jschon.URI(str)

        # TODO: Don't hardcode 3.0
        resource = self._manager.get_oas(resource_uri, '3.0')
        assert resource is not None
        document = resource.document_root
        sourcemap = resource.sourcemap

        self._g.add_resource(document.url, document.uri)

        try:
            output = sp.parse(resource, oastype)
        except JsonSchemaParseError as e:
            errors.append({
                'location': str(resource.pointer_uri),
                'stage': 'JSON Schema validation',
                'error': e.error_detail,
            })
            return errors

        to_validate = {}
        by_method = defaultdict(list)
        for unit in output['annotations']:
            ann=Annotation(unit, instance_base=resource_uri.copy(fragment=None))
            method = f'add_{ann.keyword.lower()}'

            # Using a try/except here can result in confusion if something
            # else produces an AttributeError, so use hasattr()
            if hasattr(self._g, method):
                by_method[method].append((ann, document, resource, sourcemap))
            else:
                raise ValueError(f"Unexpected annotation {ann.keyword!r}")
        self._validated.append(resource_uri)

        for annot in ANNOT_ORDER:
            if annot == 'oasExamples':
                # By this point we have set up the necessary reference info
                for uri, oastype in to_validate.items():
                    if uri not in self._validated:
                        errors.extend(self.validate(
                            uri,
                            oastype,
                            validate_examples=validate_examples,
                        ))
                if not validate_examples:
                    logger.info('Skipping example validation')
                    continue

            method_name = f'add_{annot.lower()}'
            method_callable = getattr(self._g, method_name)
            for args in by_method[method_name]:
                graph_result = method_callable(*args)
                for err in graph_result.errors:
                    errors.append(err)
                for uri, oastype in graph_result.refTargets:
                    to_validate[uri] = oastype

        return errors

    def validate_graph(self):
        errors = []
        errors.extend(self._g.validate_json_references())
        return errors

    def get_oas_graph(self) -> OasGraph:
        return self._g
