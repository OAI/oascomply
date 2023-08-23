import os
import sys
import json
import re
from typing import (
    Any, FrozenSet, Iterator, Literal, Optional, Sequence, TypeVar, Union,
)
import logging

import rdflib
import toml
import dom_toml
import yaml
import pygments
import pygments.lexers
import pygments.formatters
from rdflib.namespace import RDF, RDFS, XSD

import oascomply
from oascomply.oasgraph import OasGraph


__all__ = [
    'OASSerializer',
    'RDFOutputLineFormat',
    'RDFOutputStructuredFormat',
    'RDFOutputFormat',
    'OutputFormat',
    'RDF_OUTPUT_FORMATS_LINE',
    'RDF_OUTPUT_FORMATS_STRUCTURED',
    'RDF_OUTPUT_FORMATS',
    'OUTPUT_FORMATS',
]


logger = logging.getLogger(__name__)


RDFOutputLineFormat: TypeVar = Literal[
    'nt11',                     # N-Triples UTF-8 encoded (default)
    'nt',                       # N-Triples
    'ntriples',                 # N-Triples
    'application/n-triples',    # N-Triples
    'nquads',                   # N-Quads
    'application/n-quads',      # N-Quads
    'hext',                     # Hextuples in NDJSON
]

RDFOutputStructuredFormat: TypeVar = Literal[
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
]

RDFOutputFormat: TypeVar = Union[RDFOutputLineFormat, RDFOutputStructuredFormat]

OutputFormat: TypeVar = Union[RDFOutputFormat, Literal['toml']]

RDF_OUTPUT_FORMATS_LINE: FrozenSet = frozenset(RDFOutputLineFormat.__args__)
RDF_OUTPUT_FORMATS_STRUCTURED: FrozenSet = frozenset(
    RDFOutputStructuredFormat.__args__,
)
RDF_OUTPUT_FORMATS: FrozenSet = (
    RDF_OUTPUT_FORMATS_LINE | RDF_OUTPUT_FORMATS_STRUCTURED
)
OUTPUT_FORMATS: FrozenSet = RDF_OUTPUT_FORMATS | {'toml'}


OUTPUT_FORMAT_LEXERS = {
    'ttl': pygments.lexers.TurtleLexer,
    'turtle': pygments.lexers.TurtleLexer,
    'text/turtle': pygments.lexers.TurtleLexer,
    'longturtle': pygments.lexers.TurtleLexer,
    'ttl2': pygments.lexers.TurtleLexer,
    'nt': pygments.lexers.TurtleLexer,
    'nt11': pygments.lexers.TurtleLexer,
    'ntriples': pygments.lexers.TurtleLexer,
    'application/n-triples': pygments.lexers.TurtleLexer,
    'json-ld': pygments.lexers.JsonLdLexer,
    'application/ld+json': pygments.lexers.JsonLdLexer,
    'xml': pygments.lexers.XmlLexer,
    'application/rdf+xml': pygments.lexers.XmlLexer,
    'pretty-xml': pygments.lexers.XmlLexer,
    'trix': pygments.lexers.XmlLexer,
    'application/trix': pygments.lexers.XmlLexer,
    'hext': pygments.lexers.JsonLexer,
    'toml': pygments.lexers.TOMLLexer,
}


# An incomplete set, containing only those the author subjectively
# finds to be at least somewhat aesthetically appealing
OutputStyle: TypeVar = Literal[
    'paraiso-dark',     # purple and blue-green
    'material',         # mauve and green-yellow
    'monokai',          # sky blue, yellow, w pink and white
    'bw',               # monochrome; uses bold, italics, etc.
    'rainbow_dash',     # blue and kelly green
    'abap',             # violet and yellow-green
    'solarized-dark',   # olive and teal
    'sas',              # violet and wine
    'stata-dark',       # gray and green
    'zenburn',          # yellow and peach
]


class OASSerializer:
    def __init__(
        self,
        destination=sys.stdout,
        output_format='nt11',
        test_mode: bool = False,
    ):
        self._dest = destination
        self._format = output_format
        self._test_mode = test_mode

    def serialize_test_mode(self) -> Optional[Union[str, Iterator[str]]]:
        if self._format and self._format != 'nt11':
            sys.stderr.write('Only "nt11" supported in test mode!\n')
            sys.exit(-1)
        if self._dest not in (None, sys.stdout):
            sys.stderr.write(
                'Only in-memory and stdout supported in test mode!\n',
            )
            sys.exit(-1)

        # TODO: At least sometimes, there is a blank line in the output.
        #       But there does not seem to be when serializeing directly
        #       to stdout.  This might be an issue with split(), in which
        #       case maybe use split()[:-1]?  Need to check performance
        #       with large graphs.
        filtered = filter(
            lambda l: l != '',
            sorted(graph.serialize(output_format='nt11').split('\n')),
        )
        if self._dest is None:
            return filtered
        for line in filtered:
            print(line, file=self._dest)
        return

    def stream_to_std_fd(self, graph, **kwargs) -> None:
        """Serialize directly to stdout/stderr."""

        # rdflib serializers write bytes, not str if self._dest
        # is not None, which doesn't work with sys.stdout / sys.stderr
        self._dest.flush()
        with os.fdopen(
            # TODO: should this work for stderr?
            sys.stdout.fileno(),
            "wb",
            closefd=False,  # Don't close stdout/err exiting the with
        ) as dest_fd:
            graph.serialize(destination=dest_fd, **kwargs)
            dest_fd.flush()
            return

    def colorize(self, data: str) -> None:
        if (lexer_cls := OUTPUT_FORMAT_LEXERS.get(self._format)) is not None:

            # self._dest.write(pygments.highlight(
            data = pygments.highlight(
                data,
                lexer=lexer_cls(),
                formatter=pygments.formatters.Terminal256Formatter(
                    # style='paraiso-dark', # purple and blue-green
                    # style='material',     # mauve and green-yellow
                    # style='monokai',      # sky blue, yellow, w pink and white
                    # style='bw',           # uses bold, italics, etc.
                    # style='rainbow_dash', # blue and kelly green
                    # style='abap',         # violet and yellow-green
                    style='solarized-dark', # olive and teal
                    # style='sas',          # violet and wine
                    # style='stata-dark',   # gray and green
                    # style='zenburn',      # yellow and peach
                ),
            )

        if isinstance(data, bytes):
            self._dest.flush()
            with os.fdopen(
                # TODO: should this work for stderr?
                sys.stdout.fileno(),
                "wb",
                closefd=False,  # Don't close stdout/err exiting the with
            ) as dest_fd:
                dest_fd.write(data)
                dest_fd.flush()
                return

        self._dest.write(data)

    def serialize(
        self,
        oas_graph: OasGraph,
        *,
        base_uri: str,
        resource_order: Sequence[str],
        **kwargs,
    ) -> Optional[Union[str, Iterator[str]]]:

        if self._test_mode:
            return self.serialize_test_mode(graph)

        # Note that only lowercase "utf-8" avoids an encoding
        # warning with N-Triples output (and possibly other
        # serializers).  rdflib doesn't understand "UTF-8", but
        # confusingly uses "UTF-8" in the warning message.
        new_kwargs = {
            'encoding': 'utf-8',
            'format': self._format,
            'order': resource_order,
        }
        logger.debug(f'Serializeing to format {self._format!r}')
        new_kwargs.update(kwargs)
        if (
            self._format not in RDF_OUTPUT_FORMATS_LINE and
            base_uri is not None
        ):
            new_kwargs['base'] = base_uri

        graph = oas_graph.get_rdf_graph()
        if (
            self._dest in (sys.stdout, sys.stderr) and
            not self._dest.isatty() and
            self._format != 'toml'
        ):
            return self.stream_to_std_fd(graph, **new_kwargs)

        elif self._format == 'toml':
            return self.to_toml(oas_graph, **new_kwargs)

        elif self._dest is None:
            return graph.serialize(
                destination=self._dest, **new_kwargs,
            )

        elif self._dest.isatty():
            return self.colorize(graph.serialize(
                destination=None, **new_kwargs,
            ))

        graph.serialize(destination=self._dest, **new_kwargs)

    def to_toml(
        self,
        oas_graph: OasGraph,
        **kwargs,   # TODO: ignored?  why is it here?
    ):
        data = {
            'namespaces': {
                'rdf': str(RDF),
                'rdfs': str(RDFS),
                'xsd': str(XSD),
                'schema': 'https://schema.org/',
                'oas': str(oas_graph.oas),
                f'oas{oas_graph.oasversion}': str(oas_graph.oas_v),
            },
        }
        graph = oas_graph.get_rdf_graph()
        nm = graph.namespace_manager
        for s in sorted(graph.subjects(unique=True)):
            s_name = self._pseudo_qname(s, graph)

            p_set = set(graph.predicates(s, unique=True))
            p_list = []
            for term in (RDF.type, RDFS.label):
                if term in p_set:
                    p_list.append(term)
                    p_set.remove(term)
            p_list.extend(sorted(p_set))

            for p in p_list:
                p_name = self._pseudo_qname(p, graph)
                data.setdefault(s_name, {})[p_name] = \
                    self._objects_to_toml(s, p, graph)

        if self._dest.isatty():
            self.colorize(toml.dumps(data))
        else:
            toml.dump(data, self._dest, dom_toml.TomlEncoder())

    def _pseudo_qname(self, term, graph): #, namespaces):
        try:
            pn_prefix, _, pn_local = \
                graph.namespace_manager.compute_qname(term, generate=False)
            return f'{pn_prefix}:{pn_local}'
        except (ValueError, KeyError):
            return str(term)

    def _objects_to_toml(self, subject, predicate, graph):
        objects = list(graph.objects(subject, predicate))
        if len(objects) > 1:
            return [self._object_to_toml(o, graph) for o in objects]
        return self._object_to_toml(objects[0], graph)

    def _object_to_toml(self, obj, graph):
        nm = graph.namespace_manager
        if isinstance(obj, rdflib.Literal):
            retval = [str(obj)]
            if obj.datatype:
                retval.append(self._pseudo_qname(obj.datatype, graph))
            return retval
        return self._pseudo_qname(obj, graph)
