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
import rfc3987
import rdflib
from rdflib.namespace import RDF, RDFS
import yaml

from oascomply.ptrtemplates import (
    RelativeJSONPointerTemplate,
    RelativeJSONPointerTemplateError,
)
from oascomply.oas30dialect import OAS30_DIALECT_METASCHEMA

__all__ = [
    'OasGraph',
]

logger = logging.getLogger(__name__)


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


OasGraphResult = namedtuple('Graphresult', ['errors', 'refTargets'])


class OasGraph:
    """
    Graph representing an OAS API description

    :param version: The X.Y OAS version string for the description
    """
    def __init__(self, version: str, *, test_mode=False):
        if version not in ('3.0', '3.1'):
            raise ValueError(f'OAS v{version} is not supported.')
        if version == '3.1':
            raise ValueError(f'OAS v3.1 support TBD.')
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

    @cached_property
    def oas(self):
        return self._oas_unversioned

    @cached_property
    def oas_v(self):
        return self._oas_versions[self._version]

    def serialize(self, *args, base=None, output_format=None, **kwargs):
        """Serialize the graph using the given output format."""
        kw = kwargs.copy()
        if output_format not in OUTPUT_FORMATS_LINE and base is not None:
            kw['base'] = base

        return self._g.serialize(
            *args,
            format=output_format,
            **kwargs,
        )

    def add_resource(self, location, iri):
        rdf_node = rdflib.URIRef(iri)
        if not self._test_mode:
            self._g.add((
                rdf_node,
                self.oas['locatedAt'],
                rdflib.Literal(
                    location.resolve().as_uri() if isinstance(location, Path)
                    else location,
                    datatype=XSD.anyURI,
                ),
            ))
        self._g.add((
            rdf_node,
            self.oas['root'],
            rdf_node + '#',
        ))
        filename = None
        if isinstance(location, Path):
            filename = location.name
        else:
            path = rfc3987.parse(location, rule='IRI')['path']
            if '/' in path:
                filename = path.split('/')[-1]

        if filename:
            self._g.add((
                rdf_node,
                RDFS.label,
                rdflib.Literal(f'file:{filename}'),
            ))

    def _create_label(self, location, instance, instance_uri, oastype):
        if oastype in (
            'PathOnlyTemplatedUrl', 'StatusCode', 'TemplateParameter',
        ):
            # These are handled by other types on the same node
            # TODO: Reconsider having these oastype at all
            return

        elif oastype.endswith('Operation'):
            op = location.instance_ptr.evaluate(instance)
            if 'operationId' in op:
                label = rdflib.Literal(f"Op:{op['operationId'].value}")
            else:
                label = rdflib.Literal(
                    f"Op:{location.instance_ptr[-2]}"
                    f":{location.instance_ptr[-1]}"
                )

        elif oastype in (
            'Callback', 'Encoding', 'Link', 'Response',
        ):
            label = rdflib.Literal(f"{oastype}:{location.instance_ptr[-1]}")

        elif oastype == 'MediaType':
            label = rdflib.Literal(location.instance_ptr[-1])

        elif oastype == 'PathItem':
            label = rdflib.Literal(f"Path:{location.instance_ptr[-1]}")

        elif oastype == 'SecurityRequirement':
            label = rdflib.Literal(f"SecReq:{location.instance_ptr[-1]}")

        elif oastype == 'ServerVariable':
            label = rdflib.Literal(f"Variable:{location.instance_ptr[-1]}")

        elif oastype.endswith('Parameter'):
            i = location.instance_ptr.evaluate(instance)
            label = rdflib.Literal(f"Param:{i['in']}:{i['name']}")

        elif oastype in ('Header', 'Tag'):
            i = location.instance_ptr.evaluate(instance)
            label = rdflib.Literal(f"{oastype}:{i['name'].value}")

        elif oastype == 'ExternalDocs':
            label = rdflib.Literal('ExtDocs')

        else:
            label = rdflib.Literal(oastype)

        self._g.add((
            instance_uri,
            RDFS.label,
            label,
        ))

    def add_oastype(self, annotation, instance, sourcemap):
        # to_rdf()
        instance_uri = rdflib.URIRef(str(annotation.location.instance_uri))
        self._g.add((
            instance_uri,
            RDF.type,
            self.oas_v[annotation.value],
        ))
        self._create_label(
            annotation.location,
            instance,
            instance_uri,
            annotation.value,
        )
        if sourcemap:
            self._g.add((
                instance_uri,
                RDF.type,
                self.oas['ParsedStructure'],
            ))
            self.add_sourcemap(
                instance_uri,
                annotation.location.instance_ptr,
                sourcemap,
            )
        return OasGraphResult(errors=[], refTargets=[])

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
        annotation,
        instance,
        value_processor=None,
    ):
        parent_obj = annotation.location.instance_ptr.evaluate(instance)
        for child_template, ann_value in annotation.value.items():
            rdf_name = ann_value.value
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
                for result in RelativeJSONPointerTemplate(
                    child_template,
                ).evaluate(parent_obj)
            )

    def _flatten_template_array(
            self,
            location,
            template_array,
            instance,
    ):
        return chain.from_iterable((
            (
                r for r in RelativeJSONPointerTemplate(t).evaluate(instance)
            )
            for t in template_array
        ))

    def add_oaschildren(self, annotation, instance, sourcemap):
        location = annotation.location
        # to_rdf()
        parent_uri = rdflib.URIRef(str(location.instance_uri))
        try:
            for result, relname in self._resolve_child_template(
                annotation,
                instance,
        ):
                child_obj = result.data
                child_path = child_obj.path
                iu = location.instance_uri
                # replace fragment; to_rdf
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
            jschon.RelativeJSONPointerError,
            RelativeJSONPointerTemplateError,
        ) as e:
            # TODO: actual error handling
            raise

    def add_oasliterals(self, annotation, instance, sourcemap):
        location = annotation.location
        # to_rdf()
        parent_uri = rdflib.URIRef(str(location.instance_uri))
        try:
            for result, relname in self._resolve_child_template(
                annotation,
                instance,
            ):
                literal = result.data
                literal_path = literal.path
                literal_node = rdflib.Literal(literal.value)
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
            jschon.RelativeJSONPointerError,
            RelativeJSONPointerTemplateError,
        ) as e:
            # TODO: actual error handling
            raise

    def add_oasapilinks(self, annotation, instance, sourcemap):
        return self._add_links(
            annotation, instance, sourcemap, 'Endpoint',
        )

    def add_oasdescriptionlinks(self, annotation, instance, sourcemap):
        return self._add_links(
            annotation, instance, sourcemap, 'ExternalResource',
        )

    def _add_links(self, annotation, instance, sourcemap, entity):
        location = annotation.location
        # to_rdf()
        parent_uri = rdflib.URIRef(str(location.instance_uri))
        try:
            for result, relname in self._resolve_child_template(
                annotation,
                instance,
        ):
                link_obj = result.data
                link_path = link_obj.path
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
            jschon.RelativeJSONPointerError,
            RelativeJSONPointerTemplateError,
        ) as e:
            # TODO: actual error handling
            raise

    def add_oasreferences(self, annotation, instance, sourcemap):
        location = annotation.location
        remote_resources = []
        try:
            for template_result, reftype in self._resolve_child_template(
                annotation,
                instance,
            ):
                ref_obj = template_result.data
                ref_source_path = ref_obj.path
                iu = location.instance_uri
                # replace fragment; to_rdf
                ref_src_uri = rdflib.URIRef(str(
                    iu.copy(fragment=ref_source_path.uri_fragment())
                ))
                ref_target_uri = rdflib.URIRef(str(
                    jschon.URI(ref_obj.value).resolve(iu)
                ))
                self._g.add((
                    ref_src_uri,
                    self.oas['references'],
                    ref_target_uri,
                ))
                # TODO: elide the reference with a new edge

                # compare absolute forms
                if ref_src_uri.defrag() != ref_target_uri.defrag():
                    if reftype is True:
                        # TODO: Handle this correctly, for now just
                        #       assume Schema as a test run.
                        reftype = 'Schema'
                    remote_resources.append((str(ref_target_uri), reftype))
                if sourcemap:
                    self.add_sourcemap(
                        ref_src_uri,
                        ref_source_path,
                        sourcemap,
                    )

            return OasGraphResult(errors=[], refTargets=remote_resources)

        except (
            ValueError,
            jschon.RelativeJSONPointerError,
            RelativeJSONPointerTemplateError,
        ) as e:
            # TODO: Actual error handling
            pass

    def _build_example_schema(
        self,
        schema_data,
        metaschema_uri,
        components,
        location,
    ):
        assert 'components' not in schema_data
        patched_data = schema_data.copy()
        patched_data['components'] = {}
        patched_data['components']['schemas'] = components
        # TODO: This $id is also a problematic workaround,
        #       as it gives all example schemas the same URI
        #       as the whole OAS file, which will be confusing
        #       in any error output.
        patched_data['$id'] = str(location.instance_resource_uri)
        return jschon.JSONSchema(
            patched_data,
            metaschema_uri=metaschema_uri,
        )

    def add_oasexamples(self, annotation, instance, sourcemap):
        errors = []
        location = annotation.location
        schema_components = instance.get('components', {}).get('schemas', {})
        if schema_components:
            # This is a jschon.JSON object, so unwrap it
            schema_components = schema_components.value

        parent_obj = location.instance_ptr.evaluate(instance)
        m_uri = jschon.URI(OAS30_DIALECT_METASCHEMA)
        schemas = [
            self._build_example_schema(
                schema_data.value,
                metaschema_uri=m_uri,
                components=schema_components,
                location=location,
            )
            for schema_data in (
                (result.data for result in self._flatten_template_array(
                    location,
                    annotation.value['schemas'].value,
                    parent_obj,
                ))
                if 'schemas' in annotation.value
                else [parent_obj]
            )
        ]

        # TODO: Handle encoding objects
        try:
            for result in self._flatten_template_array(
                location,
                annotation.value['examples'].value,
                parent_obj,
            ):
                example = result.data
                for schema in schemas:
                    schema_result = schema.evaluate(example)
                    if not schema_result.valid:
                        errors.append({
                            'location': location,
                            'error': schema_result.output('detailed'),
                        })
            assert errors == []
            return OasGraphResult(errors=errors, refTargets=[])

        except (
            jschon.RelativeJSONPointerError,
            RelativeJSONPointerTemplateError,
        ) as e:
            # TODO: actual error handling
            raise

    def add_oasextensible(self, annotation, instance, sourcemap):
        if annotation.value is True:
            # to_rdf()
            parent_uri = rdflib.URIRef(str(annotation.location.instance_uri))
            parent_obj = annotation.location.instance_ptr.evaluate(instance)
            self._g.add((
                parent_uri,
                self.oas['allowsExtensions'],
                rdflib.Literal(True),
            ))
            return OasGraphResult(errors=[], refTargets=[])
