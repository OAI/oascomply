import json
import re
from functools import cached_property
from pathlib import Path
from uuid import uuid4
from typing import Any, Optional
import logging

import jschon
import rfc3987
import rdflib
from rdflib.namespace import RDF
import yaml

from oascomply.ptrtemplates import (
    RelativeJSONPointerTemplate,
    RelativeJSONPointerTemplateError,
)

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
                rdflib.URIRef(
                    location.resolve().as_uri() if isinstance(location, Path)
                    else location,
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
                self.oas['filename'],
                rdflib.Literal(filename),
            ))

    def add_oastype(self, annotation, instance, sourcemap):
        # to_rdf()
        instance_uri = rdflib.URIRef(str(annotation.location.instance_uri))
        self._g.add((
            instance_uri,
            RDF.type,
            self.oas_v[annotation.value],
        ))
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
        parent_uri = rdflib.URIRef(str(annotation.location.instance_uri))
        parent_obj = annotation.location.instance_ptr.evaluate(instance)
        for child_template, ann_value in annotation.value.items():
            # Yield back relname unchanged?
            # Take modifier funciton?
            # double generator of some sort?
            rdf_name = ann_value.value   # unwrap jschon.JSON
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

    def add_oaschildren(self, annotation, instance, sourcemap):
        location = annotation.location
        # to_rdf()
        parent_uri = rdflib.URIRef(str(location.instance_uri))
        parent_obj = location.instance_ptr.evaluate(instance)
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
        parent_obj = location.instance_ptr.evaluate(instance)
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
        parent_obj = location.instance_ptr.evaluate(instance)
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
        except (
            ValueError,
            jschon.RelativeJSONPointerError,
            RelativeJSONPointerTemplateError,
        ) as e:
            # TODO: Actual error handling
            pass

        return remote_resources
