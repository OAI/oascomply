import re
import sys
import argparse
import logging
from collections import namedtuple
from typing import Mapping, Sequence

import oascomply.resourceid as rid

logging.basicConfig(level=logging.WARN)
logger = logging.getLogger(__name__)

# NOTE: Language tags not included as oascomply does not use them
NT_RE = re.compile(
    r'<(?P<subject>[^>]*)> '
    r'<(?P<predicate>[^>]*)> '
    r'(?:(?:<(?P<object>[^>]*)>)|'
    r'(?:"(?P<literal>[^"]*)")(?:\^\^<(?P<datatype>[^>]*)>)?) \.$'
)

NAMESPACES = {
    'XSD': 'http://www.w3.org/2001/XMLSchema#',
    'RDF': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
    'RDFS': 'http://www.w3.org/2000/01/rdf-schema#',
    'SCHEMA.ORG': 'https://schema.org/',
    'OAS': 'https://spec.openapis.org/compliance/ontology#',
}

NTLine = namedtuple(
    'NTLine',
    ('subject', 'predicate', 'object', 'literal', 'datatype'),
)

class NTriplesRegexParser:
    """
    Parse N-Triples format and write a simple namespaced equivalent

    This class is primarily intended to provide a human-friendly
    format that does not suffer from the syntax limitations of
    prefixed names in N3 (not to be confused with N-Triples) or
    derived forms such as Turtle.  Those formats do not allow
    "/", "$", or other characters common in JSON Pointer fragments.

    While the parsed data can be accessed in convenient namedtuple
    form, note that the ``rdflib`` package provides much more
    powerful access to data read from the N-Triple format.  This
    class is only suitable for basic streaming processing of the
    data on a line-by-line basis.
    """
    def __init__(
        self,
        nt_fd=sys.stdin,
        *,
        namespaces=None,
        turtle_like=False,
    ):
        self._nt_fd = nt_fd
        self._next_ns_number = 1
        self._turtle_like = turtle_like

        self.namespaces = NAMESPACES.copy()
        if namespaces:
            self.namespaces.update(namespaces)

        self.error_count = 0

    def parsed_lines(self):
        """
        Generator function for iterating over parsed NTLine tuples.

        This method and :meth:`write_line` can be used to write a
        streaming filter that produces the simplified output format.
        To convert the entire unfiltered stream, use :meth:`serialize`.
        """
        while line := self._nt_fd.readline():
            if (matched := NT_RE.match(line)) is None:
                logger.error(f'Unmatched line:\n{line}')
                self.error_count += 1
                continue

            yield NTLine(
                subject=rid.Iri(matched.group('subject')),
                predicate=rid.Iri(matched.group('predicate')),
                object=None if matched.group('object') is None
                    else rid.Iri(matched.group('object')),
                literal=matched.group('literal'),
                datatype=None if matched.group('datatype') is None
                    else rid.Iri(matched.group('datatype')),
            )

    def write_line(self, ntline, out_fd=sys.stdout):
        """
        Write an NTLine tuple to stdout in the simplified format.

        This method and :meth:`parsed_lines` can be used to write a
        streaming filter that produces the simplified output format.
        To convert the entire unfiltered stream, use :meth:`serialize`.

        This method does _not_ call ``flush()`` on the file descriptor.
        """
        out_fd.write(
            self._format_iri(ntline.subject) + ' ' +
            self._format_iri(ntline.predicate) + ' ' +
            (
                self._format_iri(ntline.object)
                if ntline.object is not None
                else  f'"{ntline.literal}"' + (
                    f' {self._format_iri(ntline.datatype)}'
                    if ntline.datatype is not None
                    else ''
                )
            ) + '\n'
        )

    def serialize(self, out_fd=sys.stdout):
        """
        Write a simplified format to the given file descriptor

        This method and :meth:`serialize` share the same input file descriptor,
        so if both are called only the first will produce condent.
        """
        for ntline in self.parsed_lines():
            self.write_line(ntline)
        out_fd.flush()

    def match_namespace(self, iri):
        iri_str = str(iri)
        for name, prefix in self.namespaces.items():
            if iri_str.startswith(prefix):
                return (
                    name.lower()
                        if self._turtle_like and name in NAMESPACES
                        else name,
                    iri_str[len(prefix):],
                )
        api_ns = 'api' if self._turtle_like else 'API_'
        prefix = str(iri.to_absolute())
        name = f'{api_ns}{self._next_ns_number}'

        self.namespaces[name] = prefix
        self._next_ns_number += 1

        return name, iri_str[len(prefix):]

    def write_namespaces(self, out_fd=sys.stdout):
        for ns, prefix in self.namespaces.items():
            if self._turtle_like and ns in NAMESPACES:
                ns = ns.lower()
            out_fd.write(f'{ns} = {prefix}\n')

    def _format_iri(self, iri):
        ns, suffix = self.match_namespace(iri)
        if ns is None:
            return f'<{iri}>'
        return (
            f'{ns}:{suffix}' if self._turtle_like
            else f'{ns}{{{suffix}}}'
        )


def regex_parse():
    """Entry point for oas-reparse script"""
    arg_parser = argparse.ArgumentParser(
        epilog='NOTE: This tool and the output format it produces are '
               'somewhat experimental, and subject to change based '
               'on feedback.',
    )
    arg_parser.add_argument(
        '-n',
        '--namespace',
        nargs=2,
        metavar=('NAMESPACE_LABEL', 'URI_PREFIX'),
        dest='namespaces',
        help='Namespaces to use in the output format; can be repeated; '
             'if prefixes overlap, the first-provided prefix is used.',
    )
    arg_parser.add_argument(
        '-t',
        '--turtle-like',
        action='store_true',
        help='Use NAMESPACE_LABEL:URI_SUFFIX format, similar to N3 or '
             'Turtle; note that the resulting output will *not* be '
             'compliant with those formats due to limitations on '
             'the URI suffix syntax that those formats impose; standard '
             'and auto-generated namespace labels will be lower-cased, '
             'while user-provided namespaces from the -n option will be '
             'used as-is',
    )
    args = arg_parser.parse_args()

    if args.namespaces:
        nt_parser = NTriplesRegexParser(
            namespaces={k: v for k, v in args.namespaces},
            turtle_like=args.turtle_like,
        )
    else:
        nt_parser = NTriplesRegexParser(
            turtle_like=args.turtle_like,
        )

    nt_parser.serialize()
    print()
    nt_parser.write_namespaces()

    if nt_parser.error_count:
        logger.error(f'{nt_parser.error_count} lines could not be parsed!')
        sys.exit(nt_parser.error_count)
