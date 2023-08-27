import sys
import json
import re
from collections import namedtuple
from functools import cached_property
from itertools import chain
from pathlib import Path
from uuid import uuid4
from typing import Any, Optional
import logging

import jschon
import jschon.exc
import rdflib
from rdflib.namespace import RDF, RDFS, XSD
import toml
import dom_toml
import yaml
import pygments
import pygments.lexers
import pygments.formatters

import oascomply
from oascomply.ptrtemplates import (
    RelJsonPtrTemplate,
    RelJsonPtrTemplateError,
)
from oascomply.oas3dialect import OAS30_DIALECT_METASCHEMA
from oascomply.resource import OASNodeBase
from oascomply.schemaparse import Location

__all__ = [
    'OasGraph',
]

logger = logging.getLogger(__name__)

OAS31_INDEX: {
    'Callback': '/$defs/callbacks-or-reference',
    'Example': '/$defs/example-or-reference',
}



OUTPUT_FORMATS_LINE = frozenset({
    'nt11',                     # N-Triples UTF-8 encoded (default)
    'nt',                       # N-Triples
    'ntriples',                 # N-Triples
    'application/n-triples',    # N-Triples
    'nquads',                   # N-Quads
    'application/n-quads',      # N-Quads
    'hext',                     # Hextuples in NDJSON
})


OUTPUT_FORMATS_STRUCTURED = frozenset({
    'ttl',                      # Turtle
    'turtle',                   # Turtle
    'text/turtle',              # Turtle
    'longturtle',               # Turtle with more space
    'ttl2',                     # Turtle with more space
    'n3',                       # Notation-3
    'text/n3',                  # Notation-3
    'json-ld',                  # JSON-LD
    'application/ld+json',      # JSON-LD
    'xml',                      # RDF/XML
    'application/rdf+xml',      # RDF/XML
    'pretty-xml',               # RDF/XML (prettier)
    'trig',                     # Trig (Turtle for quads)
    'application/trig',         # Trig (Turtle for quads)
    'trix',                     # Trix (RDF/XML for quads)
    'application/trix',         # Trix (RDF/XML for quads)
})

OUTPUT_FORMAT_LEXER_NAMES = {
    'toml': 'toml',
    'ttl': 'turtle',
    'turtle': 'turtle',
    'text/turtle': 'turtle',
    'longturtle': 'turtle',
    'ttl2': 'turtle',
    'nt': 'turtle',
    'nt11': 'turtle',
    'ntriples': 'turtle',
    'application/n-triples': 'turtle',
    'json-ld': 'jsonld',
    'application/ld+json': 'jsonld',
    'xml': 'xml',
    'application/rdf+xml': 'xml',
    'pretty-xml': 'xml',
    'trix': 'xml',
    'application/trix': 'xml',
}


OasGraphResult = namedtuple('Graphresult', ['errors', 'refTargets'])
Triple = namedtuple('Triple', ['subject', 'predicate', 'object'])

class OasGraph:
    """
    Graph representing an OAS API description

    :param version: The ``X.Y`` OAS version string for the description
    """
    def __init__(self, version: str, *, test_mode=False):
        self._version = version
        self._test_mode = test_mode

        self._g = rdflib.Graph()
        self._oas_unversioned = rdflib.Namespace(
            'https://spec.openapis.org/compliance/ontology#'
        )
        self._oas_versions = {
            '3.0': rdflib.Namespace(
                'https://spec.openapis.org/compliance/ontology#3.0-'
            ),
            '3.1': rdflib.Namespace(
                'https://spec.openapis.org/compliance/ontology#3.1-'
            ),
        }
        self._g.bind('oas', self._oas_unversioned)
        self._g.bind('oas3.0', self._oas_versions['3.0'])
        self._g.bind('oas3.1', self._oas_versions['3.1'])

    @property
    def oasversion(self) -> str:
        return self._version

    @cached_property
    def oas(self):
        return self._oas_unversioned

    @cached_property
    def oas_v(self):
        return self._oas_versions[self._version]

    def get_rdf_graph(self) -> rdflib.Graph:
        return self._g

    def add_resource(self, url, uri, filename=None):
        logger.info(f'Adding resource <{uri}> loaded from <{url}> to graph')
        rdf_node = rdflib.URIRef(str(uri))
        if not self._test_mode:
            self._g.add((
                rdf_node,
                self.oas['locatedAt'],
                rdflib.Literal(str(url), datatype=XSD.anyURI),
            ))
        self._g.add((
            rdf_node,
            RDF.type,
            rdflib.URIRef('https://schema.org/DigitalDocument'),
        ))
        self._g.add((
            rdf_node,
            self.oas['root'],
            rdf_node + '#',
        ))
        if filename is None:
            if '/' in url.path and not url.path.endswith('/'):
                filename = url.path.split('/')[-1]

        if filename:
            self._g.add((
                rdf_node,
                RDFS.label,
                rdflib.Literal(filename),
            ))

    def _create_label(self, location, document, data, instance_uri, oastype):
        if oastype in (
            'PathOnlyTemplatedUrl', 'StatusCode', 'TemplateParameter',
        ):
            # These are handled by other types on the same node
            # TODO: Reconsider having these oastype at all
            return

        elif oastype.endswith('Operation'):
            op = location.instance_ptr.evaluate(document)
            if 'operationId' in op:
                label = rdflib.Literal(f"Op:{op['operationId'].value}")
            else:
                label = rdflib.Literal(
                    (
                        f"Op:{location.instance_ptr[-2]}"
                        f":{location.instance_ptr[-1]}"
                    ) if len(location.instance_ptr) >= 2
                    else f"Op:{location.instance_ptr[-1]}"
                )

        elif oastype in (
            'Callback', 'Encoding', 'Link', 'Response',
        ):
            try:
                label = rdflib.Literal(f"{oastype}:{location.instance_ptr[-1]}")
            except IndexError:
                # TODO: handle path item at root of file
                label = None

        elif oastype in ('Header', 'MediaType'):
            label = rdflib.Literal(location.instance_ptr[-1])

        elif oastype == 'PathItem':
            try:
                label = rdflib.Literal(f"Path:{location.instance_ptr[-1]}")
            except IndexError:
                # TODO: handle path item at root of file
                label = None

        elif oastype == 'SecurityRequirement':
            label = rdflib.Literal(f"SecReq:{location.instance_ptr[-1]}")

        elif oastype == 'ServerVariable':
            label = rdflib.Literal(f"Variable:{location.instance_ptr[-1]}")

        elif oastype.endswith('Parameter'):
            i = location.instance_ptr.evaluate(document)
            label = rdflib.Literal(f"Param:{i['in']}:{i['name'].value}")

        elif oastype == 'Tag':
            i = location.instance_ptr.evaluate(document)
            label = rdflib.Literal(f"{oastype}:{i['name'].value}")

        elif oastype == 'ExternalDocs':
            label = rdflib.Literal('ExtDocs')

        else:
            label = rdflib.Literal(oastype)

        if label is not None:
            self._g.add((
                instance_uri,
                RDFS.label,
                label,
            ))

    def add_oastype(self, value, location, document, data, sourcemap):
        instance_uri = rdflib.URIRef(str(location.instance_uri))
        self._g.add((
            instance_uri,
            RDF.type,
            self.oas_v[value],
        ))
        self._create_label(
            location,
            document,
            data,
            instance_uri,
            value,
        )
        if sourcemap:
            self._g.add((
                instance_uri,
                RDF.type,
                self.oas['ParsedStructure'],
            ))
            self.add_sourcemap(
                instance_uri,
                location.instance_ptr,
                sourcemap,
            )
        return OasGraphResult(errors=[], refTargets=[])

    def add_oastypegroup(self, value, location, document, data, sourcemap):
        # TODO: Handle separately
        return self.add_oastype(value, location, document, data, sourcemap)

    def add_oasintermediate(self, value, location, *args):
        # TODO: don't reference internal field.
        int_base = location._given_base.copy(query='nodetype=intermediate')
        int_location = Location.get(location._unit, int_base)
        errors = []
        refTargets = []
        for annotation in value:
            logger.debug(f'oasIntermediate: {annotation!r}={value[annotation]!r}')
            if annotation == 'intermediateRelation':
                result = self.add_oaschildren(
                    {'0': 'operations'},
                    int_location,
                    *args,
                )
            elif annotation == 'oasTypeGroup':
                result = self.add_oastypegroup(
                    value[annotation],
                    int_location,
                    *args,
                )
            elif annotation == 'oasChildren':
                result = self.add_oaschildren(
                    value[annotation],
                    int_location,
                    *args,
                )
            elif annotation == 'oasLiterals':
                result = self.add_oasliterals(
                    value[annotation],
                    int_location,
                    *args,
                )
            elif annotation == 'oasReferences':
                result = self.add_oasreferences(
                    value[annotation],
                    int_location,
                    *args,
                )
            elif annotation == 'oasIntermediate':
                result = self.add_oasintermediate(
                    value[annotation],
                    int_location,
                    *args,
                )
            else:
                raise ValueError(
                    f"Unexpected oasIntermediate annotation {annotation!r}",
                )
            errors.extend(result.errors)
            refTargets.extend(result.refTargets)
        return OasGraphResult(errors=errors, refTargets=refTargets)

    def add_sourcemap(self, instance_rdf_uri, instance_ptr, sourcemap):
            if len(instance_ptr):
                map_key = '/' + '/'.join(instance_ptr)
            else:
                map_key = ''
            entry = sourcemap[map_key]
            self._g.add((
                instance_rdf_uri,
                self.oas['line'],
                rdflib.Literal(entry.value_start.line),
            ))
            self._g.add((
                instance_rdf_uri,
                self.oas['column'],
                rdflib.Literal(entry.value_start.column),
            ))

    def _resolve_child_template(
        self,
        value, location,
        document,
        data,
        value_processor=None,
    ):
        logger.debug(f'Resolving templates {list(value.items())}...')
        parent_obj = location.instance_ptr.evaluate(document)
        logger.debug(f'...parent object {parent_obj.pointer_uri}')
        for child_template, rdf_name in value.items():
            relptr = None
            if re.match(r'\d', rdf_name):
                relptr = jschon.RelativeJSONPointer(rdf_name)
                rdf_name = None

            yield from (
                (
                    result,
                    rdf_name if rdf_name
                        else relptr.evaluate(result.data),
                )
                for result in RelJsonPtrTemplate(
                    child_template,
                ).evaluate(parent_obj)
            )

    def _flatten_template_array(
            self,
            location,
            template_array,
            data,
    ):
        return chain.from_iterable((
            (
                r for r in RelJsonPtrTemplate(t).evaluate(data)
            )
            for t in template_array
        ))

    def add_oaschildren(self, value, location, document, data, sourcemap):
        parent_uri = rdflib.URIRef(str(location.instance_uri))
        try:
            for result, relname in self._resolve_child_template(
                value, location,
                document,
                data,
        ):
                child_obj = result.data
                child_path = jschon.JSONPointer(child_obj.path)
                iu = location.instance_uri
                child_uri = rdflib.URIRef(str(iu.copy(
                    fragment=child_path.uri_fragment(),
                )))
                self._g.add((
                    parent_uri,
                    self.oas[relname],
                    child_uri,
                ))
                self._g.add((
                    child_uri,
                    self.oas['parent'],
                    parent_uri,
                ))
                if sourcemap:
                    self.add_sourcemap(
                        child_uri,
                        child_path,
                        sourcemap,
                    )
            return OasGraphResult(errors=[], refTargets=[])
        except (
            jschon.exc.JSONPointerError,
            RelJsonPtrTemplateError,
        ) as e:
            # TODO: actual error handling
            raise

    def add_oasliterals(self, value, location, document, data, sourcemap):
        parent_uri = rdflib.URIRef(str(location.instance_uri))
        try:
            for result, relname in self._resolve_child_template(
                value, location,
                document,
                data,
            ):
                literal = result.data
                literal_path = jschon.JSONPointer(literal.path)
                literal_node = (
                    rdflib.Literal(literal.value, datatype=RDF.JSON)
                    if literal.type in ('object', 'array')
                    else rdflib.Literal(literal.value)
                )
                self._g.add((
                    parent_uri,
                    self.oas[relname],
                    literal_node,
                ))
                # TODO: Sourcemap for literals?  might need
                #       intermediate node as literals cannot
                #       be subjects in triples.
            return OasGraphResult(errors=[], refTargets=[])
        except (
            jschon.exc.JSONPointerError,
            RelJsonPtrTemplateError,
        ) as e:
            # TODO: actual error handling
            raise

    def add_oasapilinks(self, value, location, document, data, sourcemap):
        return self._add_links(
            value, location, document, data, sourcemap, 'Endpoint',
        )

    def add_oasdescriptionlinks(self, value, location, document, data, sourcemap):
        return self._add_links(
            value, location, document, data, sourcemap, 'ExternalResource',
        )

    def _add_links(self, value, location, document, data, sourcemap, entity):
        parent_uri = rdflib.URIRef(str(location.instance_uri))
        try:
            for result, relname in self._resolve_child_template(
                value, location,
                document,
                data,
        ):
                link_obj = result.data
                link_path = jschon.JSONPointer(link_obj.path)
                link_uri = rdflib.URIRef(str(link_obj.value))
                self._g.add((
                    parent_uri,
                    self.oas[relname],
                    link_uri,
                ))
                self._g.add((
                    link_uri,
                    RDF.type,
                    self.oas[entity],
                ))
            return OasGraphResult(errors=[], refTargets=[])
        except (
            jschon.exc.JSONPointerError,
            RelJsonPtrTemplateError,
        ) as e:
            # TODO: actual error handling
            raise

    def add_oasreferences(self, value, location, document, data, sourcemap):
        remote_resources = []
        try:
            for template_result, reftype in self._resolve_child_template(
                value, location,
                document,
                data,
            ):
                ref_keyword = template_result.pointer.path[-1]
                ref_source_uri = location.instance_uri.copy(
                    fragment=jschon.JSONPointer(
                        template_result.data.path,
                    ).uri_fragment(),
                )
                ref_uri_ref = jschon.URI(template_result.data.value)
                ref_target_uri = ref_uri_ref.resolve(location.instance_uri)

                rdf_ref_source_uri = rdflib.URIRef(str(ref_source_uri))
                rdf_ref_target_uri = rdflib.URIRef(str(ref_target_uri))
                rdf_ref_value = rdflib.Literal(
                    str(ref_uri_ref),
                    datatype=XSD.anyURI
                )
                self._g.add((
                    rdf_ref_source_uri,
                    RDF.type,
                    self.oas['JSONReference'],
                ))
                self._g.add((
                    rdflib.URIRef(str(location.instance_uri)),
                    self.oas[ref_keyword],
                    rdf_ref_source_uri,
                ))
                self._g.add((
                    rdf_ref_source_uri,
                    self.oas['references'],
                    rdf_ref_target_uri,
                ))
                self._g.add((
                    rdf_ref_source_uri,
                    self.oas['referenceValue'],
                    rdf_ref_value,
                ))
                self._g.add((
                    rdf_ref_source_uri,
                    RDFS.label,
                    rdf_ref_value,
                ))
                self._g.add((
                    rdf_ref_source_uri,
                    self.oas['referenceBase'],
                    rdflib.Literal(
                        rdflib.URIRef(
                            str(location.instance_uri.copy(fragment=None))
                        ),
                        datatype=XSD.anyURI,
                    ),
                ))
                self._g.add((
                    rdf_ref_source_uri,
                    self.oas['targetType'],
                    rdflib.Literal(reftype),
                ))

                # TODO: elide the reference with a new edge w/correct predicate

                # compare absolute forms
                if ref_source_uri.copy(fragment=None) != ref_target_uri.copy(fragment=None):
                    # TODO: Schema validation even if local?
                    #       Currently checking with semantic validation
                    logger.debug(
                        f'Reference from <{ref_source_uri}> to <{ref_target_uri}>, oastype={reftype} .',
                    )
                    remote_resources.append((ref_target_uri, reftype))
                if sourcemap:
                    self.add_sourcemap(
                        rdf_ref_source_uri,
                        ref_source_path,
                        sourcemap,
                    )

            return OasGraphResult(errors=[], refTargets=remote_resources)

        except (
            ValueError,
            jschon.exc.JSONPointerError,
            RelJsonPtrTemplateError,
        ) as e:
            # TODO: Actual error handling
            raise

    def add_oasexamples(self, value, location, document, data, sourcemap):
        errors = []
        parent_obj = location.instance_ptr.evaluate(document)
        parent_uri = rdflib.URIRef(str(location.instance_uri))

        schemas = []
        if 'schemas' in value:
            schema_data = [
                result.data for result in self._flatten_template_array(
                    location,
                    value['schemas'],
                    parent_obj,
                )
            ]
        else:
            schema_data = [parent_obj]

        # TODO: where should this info live?  resource.OAS_SCHEMA_INFO?
        m_uri = jschon.URI(OAS30_DIALECT_METASCHEMA)
        for sd in schema_data:
            if isinstance(sd, jschon.JSONSchema):
                logger.debug(
                    f'Found example validation schema <{sd.pointer_uri}>',
                )
                schemas.append(sd)
            elif isinstance(sd, OASNodeBase):
                logger.warning(
                    f'Expected OASJSONSchema at <{sd.pointer_uri}>, '
                    f'found {type(sd).__name__} instead!',
                )
                schemas.append(
                    oascomply.catalog.get_schema(sd.uri, metaschema_uri=m_uri),
                )
                # raise ValueError(
                #     f'Got non-schema where schema expected: <{sd.uri}> '
                #     f'of type {type(sd).__name__}',
                # )
            else:
                raise ValueError(
                    f"Unknown document type '{type(sd).__name__}' "
                    f"for resource <{sd.uri}>",
                )

        # TODO: Handle encoding objects
        if 'encodings' in value and len(list(
            self._flatten_template_array(
                location, value['encodings'], parent_obj,
            )
        )):
            logger.warning(
                'Validating examples/defaut with Encoding Objects '
                'not yet supported',
            )
            return OasGraphResult(errors=errors, refTargets=[])

        try:
            for result in self._flatten_template_array(
                location,
                value['examples'],
                parent_obj,
            ):
                example = result.data
                relname = (
                    'default' if result.pointer.path[-1] == 'default'
                    else 'example'
                )
                self._g.add((
                    parent_uri,
                    self.oas[relname],
                    rdflib.Literal(str(example), datatype=RDF.JSON),
                ))
                for schema in schemas:
                    ex_uri = location.instance_resource_uri.copy(
                        fragment=result.pointer.path.uri_fragment(),
                    )
                    logger.info(
                        f'Validating "{relname}" {ex_uri} against schema '
                        f'{schema.uri}, metaschema {schema.metaschema_uri}'
                    )
                    schema_result = schema.evaluate(example)
                    if not schema_result.valid:
                        errors.append({
                            'location': location,
                            'stage': 'Example and Default validation',
                            'error': schema_result.output('detailed'),
                        })
            return OasGraphResult(errors=errors, refTargets=[])

        except (
            jschon.CatalogError,
            jschon.exc.JSONPointerError,
            RelJsonPtrTemplateError,
        ) as e:
            # TODO: actual error handling
            raise

    def add_oasextensible(self, value, location, document, data, sourcemap):
        if value is True:
            parent_uri = rdflib.URIRef(str(location.instance_uri))
            parent_obj = location.instance_ptr.evaluate(document)
            self._g.add((
                parent_uri,
                self.oas['allowsExtensions'],
                rdflib.Literal(True),
            ))
            return OasGraphResult(errors=[], refTargets=[])

    def _check_oastype(self, subject, oastype, label):
        errors = []
        expected = (subject, RDF.type, self.oas_v[oastype])
        if expected not in self._g:
            errors.append({
                'location': 'TODO',
                'stage': 'RDF Graph validation',
                'error': {
                    'expected': [expected],
                    'actual': list(self._g.triples((subject, RDF.type, None))),
                }
            })
        return errors

    def _extract_core_type(self, node):
        logger.debug(f'Extracting core type of <{node}> ...')
        oastype = self._g.value(node, RDF.type, None)
        logger.debug(f'...Initial type: <{oastype}>')

        # TODO: This is due to the change in file:/ normalization because of the
        #       limitations of jschon.uri.URI using the rfc3986 module.
        if oastype is None and (u := jschon.URI(str(node))).fragment is None:
            logger.debug('...search by absolute URI failed, adding empty fragment')
            oastype = self._g.value(
                rdflib.URIRef(str(u.copy(fragment=''))),
                RDF.type,
                None,
            )

        if oastype == rdflib.URIRef('https://schema.org/DigitalDocument'):
            logger.debug('...reference targeted entire document')
            root_node = self._g.value(node, self.oas.root, None)
            return self._extract_core_type(root_node)

        core_type = oastype.fragment
        if core_type.startswith('3.'):
            core_type = core_type[core_type.index('-') + 1:]

        if core_type.endswith('Components'):
            core_type = core_type[:core_type.rindex('Components')]
            if core_type.endswith('s'):
                # de-pluralize
                core_type = (
                    'RequestBody' if core_type == 'RequestBodies'
                    else core_type[:-1]
                )
        elif core_type.endswith('Operation'):
            core_type = 'Operation'

        elif core_type.endswith('Parameter'):
            core_type = 'Parameter'

        if core_type == 'Reference':
            path = jschon.JSONPointer.parse_uri_fragment(
                jschon.URI(node).fragment
            )
            if len(path) == 3 and path[0] == 'components':
                core_type = path[1].title()
                if core_type == 'Requestbodies':
                    core_type = 'RequestBody'
                elif core_type.endswith('s'):
                    core_type = core_type[:-1]

        logger.debug(f'...final type: "{core_type}"')
        return core_type

    def validate_json_references(self):
        errors = []
        for json_ref_node, p, target_node in self._g.triples(
            (None, self.oas.references, None)
        ):
            logger.info(
                f"Validating reference <{json_ref_node}> to <{target_node}>",
            )
            context_node, context_rel, expected = None, None, None
            if ref_node := self._g.value(
                None, self.oas['$ref'], json_ref_node,
            ):
                if reference_error := self._check_oastype(
                    ref_node, 'Reference', '$ref'
                ):
                    path_item_error = self._check_oastype(
                        ref_node, 'PathItem', '$ref'
                    )
                    # TODO: figure out which error to report better
                    #       for now just use Reference as it is more common
                    if path_item_error:
                        errors.append(reference_error)
                    else:
                        # "$ref" embedded directy in Path Item node
                        context_node = ref_node

            elif ref_node := self._g.value(
                None, self.oas.operationRef, json_ref_node
            ):
                errors.extend(
                    self._check_oastype(ref_node, 'Link', 'operationRef')
                )
                # operationRef embedded directly in Link node, to Operation
                context_node = ref_node
                expected = 'Operation'

            else:
                errors.append({
                    'location': 'TODO',
                    'stage': 'RDF Graph validation',
                    'error': f'unexpected reference type for {json_ref_node}',
                })

            if context_node is None:
                # Reference Objects sit in place of the context node,
                # so use the target type from the schema annotation.
                # TODO: This is a bit circular as that annotation type
                #       is how we choose the validation schema.  Is there
                #       a better way to check this?
                parent_node = self._g.value(ref_node, self.oas.parent, None)
                context_rel = self._g.value(parent_node, None, ref_node)
                expected = self._g.value(json_ref_node, self.oas.targetType, None)
            elif expected is None:
                expected = self._extract_core_type(context_node)

            context = {}
            if context_rel:
                context['relation'] = context_rel
            if context_node:
                context['node'] = context_node

            logger.debug(f'...reference target node: {target_node}')
            actual = self.oas_v[self._extract_core_type(target_node)]
            expected = self.oas_v[expected]
            if expected != actual:
                errors.append({
                    'location': 'TODO',
                    'stage': 'RDF Graph validation',
                    'error': {
                        'json_reference': json_ref_node,
                        'reference_context': context,
                        'reference_target': target_node,
                        'expected': (
                                target_node, RDF.type, expected,
                        ),
                        'actual': (
                                target_node, RDF.type, actual,
                        ),
                    }
                })

        return errors
