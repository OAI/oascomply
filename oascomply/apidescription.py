import json
from collections import defaultdict
from typing import (
    Any, Iterator, Mapping, Optional, Sequence, Tuple, Type, Union
)
import logging

import oascomply
from oascomply.oasgraph import OasGraph
from oascomply.schemaparse import (
    Annotation, SchemaParser, JsonSchemaParseError,
)
from oascomply.resource import OASResourceManager, URI

__all__ = [
    'ApiDescription',
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
    def base_uri(self) -> URI:
        """
        The base URI for the overal API document set.

        This is used in some output serialization formats.
        """
        return self._base_uri

    @property
    def validated_resources(self) -> Tuple[URI]:
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
            resource = self._manager.get_oas(resource_uri)
        else:
            if isinstance(resource_uri, str):
                resource_uri = URI(str)
            resource = self._manager.get_oas(
                resource_uri,
                oasversion=self._primary_resource.oasversion,
                oastype=oastype,
            )

        assert resource is not None
        document = resource.document_root
        sourcemap = resource.sourcemap

        self._g.add_resource(document.url, document.uri)

        self._manager.preload_resources(self._primary_resource.oasversion)
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
            ann=Annotation(
                unit,
                instance_base=resource_uri.copy(fragment=None),
            )
            method = f'add_{ann.keyword.lower()}'

            # Using a try/except here can result in confusion if something
            # else produces an AttributeError, so use hasattr()
            if hasattr(self._g, method):
                by_method[method].append((ann, document, resource, sourcemap))
            else:
                raise ValueError(f"Unexpected annotation {ann.keyword!r}")
        self._validated.append(resource_uri)
        self._manager._catalog.resolve_references()

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
