import json
from pathlib import Path
from uuid import uuid4
from typing import Any, Optional
import logging

import jschon
import rfc3987
import rdflib
from rdflib.namespace import RDF
import yaml

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
    def __init__(self, version):
        if version not in ('3.0', '3.1'):
            raise ValueError(f'OAS v{version} is not supported.')
        if version == '3.1':
            raise ValueError(f'OAS v3.1 support TBD.')

        self._g = rdflib.Graph()
        self._oas = rdflib.Namespace(
            f'https://spec.openapis.org/oas/v{version}/ontology#'
        )
        self._g.bind('oas3.0', self._oas)

    def serialize(self, *args, base=None, output_format=None, **kwargs):
        """Serialize the graph if and only if an output format is requested."""
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
        self._g.add((
            rdf_node,
            self._oas['locatedAt'],
            rdflib.URIRef(
                location.resolve().as_uri() if isinstance(location, Path)
                else location,
            ),
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
                self._oas['filename'],
                rdflib.Literal(filename),
            ))

    def add_oastype(self, annotation, instance, sourcemap):
        # to_rdf()
        instance_uri = rdflib.URIRef(str(annotation.location.instance_uri))
        self._g.add((
            instance_uri,
            RDF.type,
            self._oas[annotation.value],
        ))
        self._g.add((
            instance_uri,
            RDF.type,
            self._oas['ParsedStructure'],
        ))
        if sourcemap:
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
                self._oas['line'],
                rdflib.Literal(entry.value_start.line),
            ))
            self._g.add((
                instance_rdf_uri,
                self._oas['column'],
                rdflib.Literal(entry.value_start.column),
            ))

    def add_oaschildren(self, annotation, instance, sourcemap):
        location = annotation.location
        # to_rdf()
        parent_uri = rdflib.URIRef(str(location.instance_uri))
        for child in annotation.value:
            child = child.value
            if '{' in child:
                continue

            child_ptr = jschon.RelativeJSONPointer(child)
            parent_obj = location.instance_ptr.evaluate(instance)
            try:
                child_obj = child_ptr.evaluate(parent_obj)
                child_path = child_obj.path
                iu = location.instance_uri
                # replace fragment; to_rdf
                child_uri = rdflib.URIRef(str(iu.copy(
                    fragment=child_path.uri_fragment(),
                )))
                self._g.add((
                    parent_uri,
                    self._oas[child_ptr.path[0]],
                    child_uri,
                ))
                self._g.add((
                    child_uri,
                    self._oas['parent'],
                    parent_uri,
                ))
                if sourcemap:
                    self.add_sourcemap(
                        child_uri,
                        child_path,
                        sourcemap,
                    )
            except jschon.RelativeJSONPointerError as e:
                pass

    def add_oasreferences(self, annotation, instance, sourcemap):
        location = annotation.location
        remote_resources = []
        for refloc, reftype in annotation.value.items():
            reftype = reftype.value
            # if '{' in refloc:
                # continue
            try:
                ref_ptr = jschon.RelativeJSONPointer(refloc)
                parent_obj = location.instance_ptr.evaluate(instance)
                ref_obj = ref_ptr.evaluate(parent_obj)
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
                    self._oas['references'],
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
            except (ValueError, jschon.RelativeJSONPointerError) as e:
                pass
        return remote_resources
