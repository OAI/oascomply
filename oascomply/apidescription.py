import argparse
import re
import json
from pathlib import Path
import urllib
from uuid import uuid4
from collections import defaultdict, namedtuple
from typing import (
    Any, Iterator, Mapping, Optional, Sequence, Tuple, Type, Union
)
import logging
import os
import sys

import jschon

import rdflib
from rdflib.namespace import RDF

import oascomply
from oascomply.oasgraph import (
    OasGraph, OasGraphResult, OUTPUT_FORMATS_LINE, OUTPUT_FORMATS_STRUCTURED,
)
from oascomply.schemaparse import (
    Annotation, SchemaParser, JsonSchemaParseError,
)
from oascomply.oassource import (
    DirectMapSource, FileMultiSuffixSource, HttpMultiSuffixSource,
)
from oascomply.oas3dialect import OAS30_DIALECT_METASCHEMA
import oascomply.resourceid as rid

__all__ = [
    'ApiDescription',
]

logger = logging.getLogger(__name__)

HELP_PROLOG = """
Load and validate an API Description/Definition (APID).

The initial APID document is parsed immediately, with other documents parsed
as they are referenced.  The initial document is the first of:

1. The document from -i (--initial-document)
2. The first document from a -f (--file) containing an "openapi" field
3. The first document from a -u (--url) containing an "openapi" field

All referenced documents MUST be provided in some form on the command line,
either individually (with -f or -u) or as a document tree to search (with
-d or -p).  Documents are loaded from their URL and referenced by their URI.

Each document's URL is the URL from which it was retrieved. If loaded from
a local filesystem path, the URL is the corresponding "file:" URL.

A document's URI is either determined from the URL (potentially as modified
by the -x, -D, and -P options), or set directly on the command line
(using additional arguments to -i, -f, -u, -d, or -p)..
This allows reference resolution to work even if the documents are not named
or deployed in the way the references expect.

See the "Loading APIDs and Schemas" tutorial for full documentation.
"""

HELP_EPILOG = """
See the README for further information on:

* How API description data appears in the output
* How to extract human-friendly names from the output
* API description document URLs vs URIs
* Handling multi-document API descriptions
* Handling complex referencing scenarios
* What you need to know about IRIs vs URIs/URLs
"""

ANNOT_ORDER = (
    'oasType',
    'oasReferences',
    'oasChildren',
    'oasLiterals',
    'oasExtensible',
    'oasApiLinks',
    'oasDescriptionLinks',
    'oasExamples',
)


UriPrefix = namedtuple('UriPrefix', ['directory', 'prefix'])
"""Utility class for option data mapping URI prefixes."""


def _add_verbose_option(parser):
    parser.add_argument(
        '-v',
        '--verbose',
        action='count',
        default=0,
        help="Increase verbosity; can passed twice for full debug output.",
    )


def _add_strip_suffixes_option(parser):
    parser.add_argument(
        '-x',
        '--strip-suffixes',
        nargs='*',
        default=('.json', '.yaml', '.yml', ''),  # TODO: not sure about ''
        help="For documents loaded with -f or -u without an explict URI "
            "assigned on the command line, assign a URI by stripping any "
            "of the given suffixes from the document's URL; passing this "
            "option without any suffixes disables this behavior, treating "
            "the unmodified URL as the URI; the default stripped suffixes "
            "are .json, .yaml, .yml",
    )


# TODO: URI vs IRI confusion... again...
class ThingToUri:
    """
    Helper class for mapping URIs to URLs and back.

    In addition to being more convenient than a tuple or dict, this class
    hierarchy handles calculating URIs from things based on various factors.

    :param values: A string or sequence of strings as in the
        :class:`argparse.Action` interface
    :param strip_suffixes: The suffixes, if any, to strip when determining
        a URI from the thing
    :param uri_is_prefix: Indicates that the URI will be used as a prefix,
        which currently requires it to have a path ending in "/".
    """
    def __init__(
        self,
        values: Union[str, Sequence[str]],
        strip_suffixes: Sequence[str] = (),
        uri_is_prefix: bool = False,
    ) -> None:
        logger.debug(
            f'Parsing location+uri option with argument {values!r}, '
            f'stripping suffixes: {strip_suffixes}',
        )
        try:
            if isinstance(values, str):
                values = [values]
            if len(values) not in (1, 2):
                raise ValueError(f'Expected 1 or 2 values, got {len(values)}')

            self._values = values
            self._to_strip = strip_suffixes
            self._uri_is_prefix = uri_is_prefix

            thing = self._set_thing(values[0])
            if len(values) == 2:
                iri_str = values[1]
                logger.debug(
                    f'Using URI <{iri_str}> from command line for "{thing}"'
                )
            else:
                iri_str = self.iri_str_from_thing(
                    self.strip_suffixes(thing),
                )
                logger.debug(
                    f'Calculated URI <{iri_str}> for "{thing}"'
                )

            if uri_is_prefix and not iri_str.endswith('/'):
                raise ValueError(
                    f"URI prefix <{iri_str}> must have a path ending in '/'",
                )

            self.set_iri(iri_str)

            if uri_is_prefix and self.uri.query or self.uri.fragment:
                raise ValueError(
                    f"URI prefix <{self.uri}> may not include "
                    "a query or fragment",
                )

            logger.info(str(self))

        except Exception:
            # argparse suppresses any exceptions that are raised, so log them
            import traceback
            from io import StringIO

            buffer = StringIO()
            traceback.print_exc(file=buffer)
            logger.warning(buffer.getvalue())

            raise

    def __repr__(self):
        return f'{self.__class__.__name__}({self._values!r})'

    @property
    def thing(self):
        """
        Generic thing accessor; subclasses should offer a more specific one.

        See non-public :meth:`_set_thing` for modifications.
        """
        return self.thing

    def __str__(self):
        return f'(thing: {self._values[0]}, uri: <{self.uri}>)'

    def strip_suffixes(self, thing: Any) -> str:
        thing_string = str(thing)
        for suffix in self._to_strip:
            if thing_string.endswith(suffix):
                return thing_string[:-len(suffix)]
        return thing_string

    def _set_thing(self, thing_str) -> Any:
        self.thing = thing_str
        return thing_str

    def set_iri(
        self,
        iri_str: str,
        iri_class: Type[rid.Iri] = rid.Iri,
        attrname: str = 'uri',
    ) -> None:
        try:
            setattr(self, attrname, iri_class(iri_str))
        except ValueError as e1:
            try:
                rid.IriReference(iri_str)
                raise ValueError(f'{iri_class.__name__} cannot be relative')
            except ValueError as e2:
                logger.debug(
                    f'got exception from IriReference({iri_str}):'
                    f'\n\t{e2}'
                )
                # propagate the original error as it will be more informative
                raise e1

    def iri_str_from_thing(self, stripped_thing_str: str) -> str:
        return stripped_thing_str


class PathToUri(ThingToUri):
    """Local filesystem path to URI utility class."""

    def __str__(self):
        return f'(path: {self.path}, uri: <{self.uri}>)'

    def _set_thing(self, thing_str: str) -> None:
        self.path = Path(thing_str).resolve()
        if self._uri_is_prefix and not self.path.is_dir():
            raise ValueError(
                f"Path '{self.path}' must be a directory when mapping "
                "to a URI prefix",
            )
        return self.path

    def iri_str_from_thing(self, stripped_thing_str: str) -> str:
        # It seems odd to rebuild the path object, but Path.with_suffix('')
        # doesn't care what suffix is removed, so we couldn't use it anyway
        return Path(stripped_thing_str).resolve().as_uri()

    @property
    def path(self) -> Path:
        """Accessor for ``path``, the "thing" of this ThingToUri subclass."""
        return self._path

    @path.setter
    def path(self, p: Path) -> None:
        self._path = p

    @property
    def thing(self) -> Any:
        return self.path


class UrlToUri(ThingToUri):
    """URL to URI utility class; does not check URL scheme or usability."""
    def __str__(self):
        return f'(url: {self.url}, uri: <{self.uri}>)'

    def _set_thing(self, thing_str: str) -> None:
        self.set_iri(thing_str, attrname='url')
        return self.url

    @property
    def url(self) -> rid.Iri:
        """Accessor for ``url``, the "thing" of this ThingToUri subclass."""
        return self._url

    @url.setter
    def url(self, u: rid.Iri) -> None:
        self._url = u

    @property
    def thing(self):
        return self.url


class CustomArgumentParser(argparse.ArgumentParser):
    def _fix_message(self, message):
        # nargs=+ does not support metavar=tuple
        return message.replace(
            'INITIAL [INITIAL ...]',
            'FILE|URL [URI]',
        ).replace(
            'FILES [FILES ...]',
            'FILE [URI] [TYPE]',
        ).replace(
            'DIRECTORIES [DIRECTORIES ...]',
            'DIRECTORY [URI_PREFIX]',
        ).replace(
            'URLS [URLS ...]',
            'URL [URI] [TYPE]',
        ).replace(
            'PREFIXES [PREFIXES ...]',
            'URL_PREFIX [URI_PREFIX]',
        )

    def format_usage(self):
        return self._fix_message(super().format_usage())

    def format_help(self):
        return self._fix_message(super().format_help())


class ActionAppendThingToUri(argparse.Action):
    @classmethod
    def make_action(
        cls,
        arg_cls: Type[ThingToUri] = ThingToUri,
        strip_suffixes: Sequence[str] = (),
    ):
        logger.debug(f'Registering {arg_cls.__name__} argument action')
        return lambda *args, **kwargs: cls(
            *args,
            arg_cls=arg_cls,
            strip_suffixes=strip_suffixes,
            **kwargs,
        )

    def __init__(
        self,
        option_strings: str,
        dest: str,
        *,
        nargs: Optional[str] = None,
        arg_cls: Type[ThingToUri],
        strip_suffixes: Sequence[str],
        **kwargs
    ) -> None:
        if nargs != '+':
            raise ValueError(
                f'{type(self).__name__}: expected nargs="+"'
            )
        self._arg_cls = arg_cls
        self._strip_suffixes = strip_suffixes
        super().__init__(option_strings, dest, nargs=nargs, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        arg_list = getattr(namespace, self.dest)
        arg_list.append(
            self._arg_cls(values, strip_suffixes=self._strip_suffixes),
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
        document: Any,
        *,
        test_mode: bool = False,
    ) -> None:
        self._primary_resource = document
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
            test_mode=test_mode,
        )

        self._validated = []

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
            resource_uri = rid.IriWithJsonPtr(resource_uri)

        # TODO: Don't hardcode 3.0
        resource = oascomply.catalog.get_oas(resource_uri, '3.0')
        assert resource is not None
        document = resource.document_root
        sourcemap = resource.sourcemap

        try:
            output = sp.parse(resource, oastype)
        except JsonSchemaParseError as e:
            logger.critical(
                f'JSON Schema validation of {resource_uri} failed!\n\n' +
                json.dumps(e.error_detail, indent=2),
            )
            sys.exit(-1)

        to_validate = {}
        by_method = defaultdict(list)
        for unit in output['annotations']:
            ann=Annotation(unit, instance_base=resource_uri.to_absolute())
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

    def serialize(
        self,
        *args,
        output_format='nt11',
        destination=sys.stdout,
        **kwargs
    ) -> Optional[Union[str, Iterator[str]]]:
        if self._test_mode:
            if output_format and output_format != 'nt11':
                sys.stderr.write('Only "nt11" supported in test mode!\n')
                sys.exit(-1)
            if destination not in (None, sys.stdout):
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
                sorted(self._g.serialize(output_format='nt11').split('\n')),
            )
            if destination is None:
                return filtered
            for line in filtered:
                print(line)
            return

        # Note that only lowercase "utf-8" avoids an encoding
        # warning with N-Triples output (and possibly other
        # serializers).  rdflib doesn't understand "UTF-8", but
        # confusingly uses "UTF-8" in the warning message.
        new_kwargs = {
            'encoding': 'utf-8',
            'base': self._base_uri,
            'output_format': output_format,
            'order': self._validated,
        }
        new_kwargs.update(kwargs)

        if destination in (sys.stdout, sys.stderr) and output_format != 'toml':
            # rdflib serializers write bytes, not str if destination
            # is not None, which doesn't work with sys.stdout / sys.stderr
            destination.flush()
            with os.fdopen(
                sys.stdout.fileno(),
                "wb",
                closefd=False,  # Don't close stdout/err exiting the with
            ) as dest:
                self._g.serialize(*args, destination=dest, **new_kwargs)
                dest.flush()
                return

        elif destination is None:
            return self._g.serialize(
                *args, destination=destination, **new_kwargs,
            )

        self._g.serialize(*args, destination=destination, **new_kwargs)

    @classmethod
    def load(cls):
        verbosity_parser = argparse.ArgumentParser(add_help=False)
        _add_verbose_option(verbosity_parser)
        v_args, remaining_args = verbosity_parser.parse_known_args()

        oascomply_logger = logging.getLogger('oascomply')
        if v_args.verbose:
            if v_args.verbose == 1:
                oascomply_logger.setLevel(logging.INFO)
            else:
                oascomply_logger.setLevel(logging.DEBUG)
        else:
            oascomply_logger.setLevel(logging.WARN)

        strip_suffixes_parser = argparse.ArgumentParser(add_help=False)
        _add_strip_suffixes_option(strip_suffixes_parser)
        ss_args, remaining_args = strip_suffixes_parser.parse_known_args(
            remaining_args,
        )

        parser = CustomArgumentParser(
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description=HELP_PROLOG,
            epilog=HELP_EPILOG,
            fromfile_prefix_chars='@',
        )
        # Already parsed, but add to include in usage message
        _add_verbose_option(parser)
        parser.add_argument(
            '-i',
            '--initial-document',
            metavar='INITIAL',
            nargs='+',
            help="NOT YET IMPLEMENTED!!! "
                "The document from which to start validating; can "
                "follow the -f or -u syntax to load the document directly "
                "and assigne or calculate a URI, or give a path under the "
                "directory of a -d option or the URL prefix of a -p argument "
                "to assign a URI based on the -d or -p's URI prefix",
        )
        parser.add_argument(
            '-f',
            '--file',
            nargs='+',
            action=ActionAppendThingToUri.make_action(
                arg_cls=PathToUri,
                strip_suffixes=ss_args.strip_suffixes,
            ),
            default=[],
            dest='files',
            help="An APID document as a local file, optionally followed by "
                 "a URI to use for reference resolution in place of the "
                 "corresponding 'file:' URL; this option can be repeated; "
                 "see also -x",
        )
        parser.add_argument(
            '-u',
            '--url',
            nargs='+',
            action=ActionAppendThingToUri.make_action(
                arg_cls=UrlToUri,
                strip_suffixes=ss_args.strip_suffixes,
            ),
            default=[],
            dest='urls',
            help="A URL for an APID document, optionally followed by a URI "
                 "to use for reference resolution; by default only 'http:' "
                 "and 'https:' URLs are supported; this option can be "
                 "repeated; see also -x",
        )
        # Already parsed, but add to include in usage message
        _add_strip_suffixes_option(parser)
        parser.add_argument(
            '-d',
            '--directory',
            nargs='+',
            action=ActionAppendThingToUri.make_action(arg_cls=PathToUri),
            default=[],
            dest='directories',
            help="Resolve references matching the URI prefix from the given "
                "directory; if no URI prefix is provided, use the 'file:' URL "
                "corresponding to the directory as the prefix; this option "
                "can be repeated; see also -D",
        )
        parser.add_argument(
            '-p',
            '--url-prefix',
            nargs='+',
            action=ActionAppendThingToUri.make_action(arg_cls=UrlToUri),
            default=[],
            dest='url_prefixes',
            help="Resolve references the URI prefix by replacing it with "
                "the given URL prefix, or directly from URLs matching the "
                "URL prefix if no URI prefix is provided; this option can be "
                "repeated; see also -P",
        )
        parser.add_argument(
            '-D',
            '--directory-suffixes',
            nargs='*',
            default=('.json', '.yaml', '.yml'),
            dest='dir_suffixes',
            help="When resolving references using -d, try appending each "
                "suffix in order to the file path until one succeeds; "
                "the empty string can be passed to try loading the "
                "unmodified path first as JSON and then if that fails as "
                "YAML; the default suffixes are .json, .yaml .yml",
        )
        parser.add_argument(
            '-P',
            '--url-prefix-suffixes',
            nargs='*',
            default=(),
            dest='url_suffixes',
            help="When resolving references using -p, try appending each "
                "suffix in order to the URL until one succeeds; the empty "
                "string can be passed to try loading the unmodified URL "
                "which will be parsed based on the HTTP Content-Type header; "
                "by default, no suffixes are appended to URLs",
        )
        parser.add_argument(
            '-n',
            '--number-lines',
            action='store_true',
            help="Enable line and column numbers in the graph and in "
                 "error reporting; this has a considerable performance "
                 "impact, especially for YAML",
        )
        parser.add_argument(
            '-e',
            '--examples',
            choices=('true', 'false'),
            default='true',
            help="Pass 'false' to disable validation of examples and defaults "
                 "by the corresponding schema.",
        )
        parser.add_argument(
            '-o',
            '--output-format',
            nargs='?',
            const='nt11',
            metavar="nt | ttl | n3 | trig | json-ld | xml | hext | ...",
            help="Serialize the parsed graph to stdout in the given format, "
                 "or 'nt11' (N-Triples with UTF-8 encoding) if no format name "
                 "is provided.  Format names are passed through to rdflib, "
                 "see that library's documentation for the full list of "
                 "options.",
        )
        parser.add_argument(
            '-O',
            '--output-file',
            help="NOT YET IMPLEMENTED "
                 "Write the output to the given file instead of stdout",
        )
        parser.add_argument(
            '-t',
            '--store',
            default='none',
            choices=(('none',)),
            help="NOT YET IMPLEMENTED "
                 "TODO: Support storing to various kinds of databases.",
        )
        parser.add_argument(
            '--test-mode',
            action='store_true',
            help="Omit data such as 'locatedAt' that will change for "
                 "every environment and produce sorted nt11 output.  "
                 "This is intended to facilitate "
                 "automated testing of the entire system.",
        )

        args = parser.parse_args(remaining_args)

        logger.debug(f'Processed arguments:\n{args}')

        # Note that if -P or -D are actually passed with
        # the args matching the default, this check will
        # still work as they will be set as a list instead
        # of the default values which are tuples
        for attr, opt, check in (
            ('initial_document', '-i', lambda arg: True),
            ('urls', '-u', lambda arg: True),
            ('url_prefixes', '-p', lambda arg: True),
            ('dir_suffixes', '-D', lambda arg: arg == (
                '.json', '.yaml', '.yml',
            )),
            ('url_suffixes', '-P', lambda arg: arg == ()),
            ('output_file', '-O', lambda arg: True),
            ('store', '-t', lambda arg: True),
        ):
            if hasattr(args, attr) and not check(getattr(args, attr)):
                raise NotImplementedError(f'{opt} option not yet implemented!')

        for dir_to_uri in args.directories:
            oascomply.catalog.add_uri_source(
                dir_to_uri.uri,
                FileMultiSuffixSource(
                    str(dir_to_uri.path), # TODO: fix type mismatch
                    suffixes=args.dir_suffixes,
                )
            )

        for url_to_uri in args.url_prefixes:
            oascomply.catalog.add_uri_source(
                url_to_uri.uri,
                HttpMultiSuffixSource(
                    str(url_to_uri.url), # TODO: fix type mismatch
                    suffixes=args.url_suffixes,
                )
            )

        resource_map = {
            f_to_u.uri: f_to_u.path
            for f_to_u in args.files
        }
        resource_map.update({
            u_to_u.uri: u_to_u.path
            for u_to_u in args.urls
        })
        oascomply.catalog.add_uri_source(
            None,
            DirectMapSource(
                resource_map,
                suffixes=('.json', '.yaml', '.yml'),
            )
        )

        # TODO: Temporary hack, search lists properly
        # TODO: Don't hardcode 3.0
        entry_resource = oascomply.catalog.get_oas(args.files[0].uri, '3.0')
        assert entry_resource['openapi'], "First file must contain 'openapi'"

        desc = ApiDescription(entry_resource, test_mode=args.test_mode)

        errors = desc.validate(validate_examples=(args.examples == 'true'))
        errors.extend(desc.validate_graph())
        if errors:
            for err in errors:
                logger.error(json.dumps(err['error'], indent=2))

            sys.stderr.write('\nAPI description contains errors\n\n')
            sys.exit(-1)

        if args.output_format is not None or args.test_mode is True:
            desc.serialize(output_format=args.output_format)

        sys.stderr.write('Your API description is valid!\n')
