import argparse
import re
import json
from pathlib import Path
import urllib
from uuid import uuid4
from collections import namedtuple
from typing import Any, Iterator, Mapping, Optional, Tuple, Union
import logging
import os
import sys

import jschon

import rdflib
from rdflib.namespace import RDF
import rfc3987
import yaml
import json_source_map as jmap
import yaml_source_map as ymap
from yaml_source_map.errors import InvalidYamlError

from oascomply.oasgraph import (
    OasGraph, OUTPUT_FORMATS_LINE, OUTPUT_FORMATS_STRUCTURED,
)
from oascomply.schemaparse import Annotation, SchemaParser

__all__ = [
    'ApiDescription',
]

logger = logging.getLogger(__name__)

HELP_EPILOG = """
See the README for further information on:

* How API description data appears in the output
* How to extract human-friendly names from the output
* API description document URLs vs URIs
* Handling multi-document API descriptions
* Handling complex referencing scenarios
* What you need to know about IRIs vs URIs/URLs
"""


UriPrefix = namedtuple('UriPrefix', ['dir', 'prefix'])

class ApiDescription:
    """
    Representation of a complete API description.

    The constructor arguments are used to load the primary API description
    resource.  This resource MUST contain an ``openapi`` field setting
    the version.  Currently, 3.0.x descriptions are supported, with 3.1.x
    support intended for a later version.
    """

    def __init__(
        self,
        data: Any,
        uri: str,
        *,
        path: Optional[Path] = None,
        url: Optional[str] = None,
        sourcemap: Optional[Mapping] = None,
        test_mode: bool = False,
    ) -> None:

        self._test_mode = test_mode

        if 'openapi' not in data:
            raise ValueError(
                "Initial API description must include `openapi` field!"
                f"{path} <{uri}>"
            )
        self._version = data['openapi']
        if not self._version.startswith('3.0.'):
            if self._version.startswith('3.1.'):
                raise NotImplementedError("OAS v3.1 support stil in progress")
            raise ValueError(f"OAS v{self._version} not supported!")

        parsed_base = rfc3987.parse(uri, rule='IRI')
        if (
            parsed_base['path'] and 
            '/' in parsed_base['path'] and
            not parsed_base['path'].endswith('/')
        ):
            # RDF serialization works better with a directory
            # as a base IRI, particularly for multi-document
            # API descriptions within a single directory.
            # Otherwise it fails to notice many opportunities to
            # shorten IRI-references.
            parsed_base['path'] = (
                parsed_base['path'][:parsed_base['path'].rindex('/') + 1]
            )
        self._base_uri=rfc3987.compose(**parsed_base)

        self._g = OasGraph(
            self._version[:self._version.rindex('.')],
            test_mode=test_mode,
        )
        self._primary_uri = uri

        self._contents = {}
        self._sources = {}
        self._validated = set()

        self.add_resource(
            data=data,
            uri=uri,
            path=path,
            sourcemap=sourcemap,
        )

    def add_resource(
        self,
        data: Any,
        uri: str,
        *,
        path: Optional[Path] = None,
        url: Optional[str] = None,
        sourcemap: Optional[Mapping] = None,
    ) -> None:
        """
        Add a resource as part of the API description, and set its URI
        for use in resolving references and in the parser's output.
        """
        # The jschon.JSON class keeps track of JSONPointer values for
        # every data entry, as well as providing parent links and type
        # information.
        self._contents[uri] = jschon.JSON(data)
        if sourcemap:
            self._sources[uri] = sourcemap
        self._g.add_resource(path, uri)

    def get(self, uri: str) -> Optional[Any]:
        try:
            return self._contents[uri], self._sources.get(uri)
        except KeyError:
            absolute, fragment = urllib.parse.urldefrag(uri)
            try:
                data = self._contents[uri]
                return (
                    jschon.JSONPointer.parse_uri_fragment(
                        fragment
                    ).evaluate(data),
                    self._sources.get(uri),
                )

            except (KeyError, jschon.JSONPointerError):
                return None, None

    def validate(self, resource_uri=None, oastype='OpenAPI'):
        sp = SchemaParser.get_parser({}, annotations=(
            'oasType',
            'oasChildren',
            'oasDescriptionLinks',
            'oasApiLinks',
            'oasReferences',
            'oasLiterals',
        ))
        if resource_uri is None:
            assert oastype == 'OpenAPI'
            resource_uri = self._primary_uri

        data, sourcemap = self.get(resource_uri)
        assert data is not None

        output = sp.parse(data, oastype)
        to_validate = {}
        for unit in output['annotations']:
            ann=Annotation(unit, instance_base=resource_uri)
            method = f'add_{ann.keyword.lower()}'

            # Using a try/except here can result in confusion if something
            # else produces an AttributeError, so use hasattr()
            if hasattr(self._g, method):
                if resources := getattr(self._g, method)(ann, data, sourcemap):
                    for uri, oastype in resources:
                        to_validate[uri] = oastype
            else:
                raise ValueError(f"Unexpected annotation {ann.keyword!r}")
        self._validated.add(resource_uri)
        for uri, oastype in to_validate.items():
            if uri not in self._validated:
                self.validate(uri, oastype)

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
        }
        new_kwargs.update(kwargs)

        if destination in (sys.stdout, sys.stderr):
            # rdflib serializers write bytes, not str # if destination
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
    def _process_resource_arg(cls, r, prefixes, create_source_map):
        path = Path(r[0])
        full_path = path.resolve()
        if len(r) > 1:
            # TODO: Support semantic type
            uri = r[1]
        else:
            uri = full_path.with_suffix('').as_uri()
        for p in prefixes:
            try:
                rel = full_path.relative_to(p.dir)
                uri = p.prefix + str(rel.with_suffix(''))
            except ValueError:
                pass
        filetype = path.suffix[1:] or 'yaml'
        if filetype == 'yml':
            filetype = 'yaml'

        content = path.read_text()
        sourcemap = None
        if filetype == 'json':
            data = json.loads(content)
            if create_source_map:
                sourcemap = jmap.calculate(content)
        elif filetype == 'yaml':
            data = yaml.safe_load(content)
            if create_source_map:
                # The YAML source mapper gets confused sometimes,
                # just log a warning and work without the map.
                try:
                    sourcemap = ymap.calculate(content)
                except InvalidYamlError:
                    logger.warn(
                        f"Unable to calculate source map for {path}",
                    )
                    pass
        else:
            raise ValueError(f"Unsupported file type {filetype!r}")

        return {
            'data': data,
            'sourcemap': sourcemap,
            'path': path,
            'uri': uri,
        }

    @classmethod
    def _process_prefix(cls, p):
        try:
            parsed = rfc3987.parse(p[0], rule='URI')
            if parsed['scheme'] == 'file':
                raise ValueError(
                    f"'file:' URIs cannot be used as URI prefixes: <{p[0]}>"
                )
            if parsed['query'] or parsed['fragment']:
                raise ValueError(
                    "URI prefixes cannot contain a query or fragment: "
                    f"<{p[0]}>"
                )
            if not parsed['path'].endswith('/'):
                raise ValueError(
                    "URI prefixes must include a path that ends with '/': "
                    f"<{p[p]}>"
                )

            path = Path(p[1]).resolve()
            if not path.is_dir():
                raise ValueError(
                    "Path mapped to URI prefix must be an existing "
                    f"directory: {p[1]!r}"
                )
            return UriPrefix(p[0], path)

        except ValueError:
            try:
                rfc3987.parse(p[0], rule='URI_reference')
                raise ValueError(f'URI prefixes cannot be relative: <{p[0]}>')
            except ValueError:
                raise ValueError(
                    f'URI prefix <{p[0]}> does not appear to be a URI'
                )

    @classmethod
    def load(cls):
        class CustomArgumentParser(argparse.ArgumentParser):
            def _fix_message(self, message):
                # nargs=+ does not support metavar=tuple
                return message.replace(
                    'FILES [FILES ...]',
                    'FILE [URI] [TYPE]',
                ).replace(
                    'DIRECTORIES [DIRECTORIES ...]',
                    'DIRECTORY [URI_PREFIX]',
                )

            def format_usage(self):
                return self._fix_message(super().format_usage())

            def format_help(self):
                return self._fix_message(super().format_help())

        parser = CustomArgumentParser(
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog=HELP_EPILOG,
        )
        parser.add_argument(
            '-f',
            '--file',
            nargs='+',
            action='append',
            dest='files',
            help="An API description file, given as a mandatory file path, "
                 "optionally followed by an URI to associate with the file, "
                 "and/or the semantic type of the file's contents, e.g. "
                 "3.1:Schema; the path MUST be first, while the URI and "
                 "semantic type can appear in either order; by default, "
                 "a 'file:' URI will be generated matching the path, "
                 "and the code will attempt to infer the semantic type "
                 "from context and reference usage.\n\n"
                 "See below for scenarios where the semantic type is required."
        )
        parser.add_argument(
            '-d',
            '--uri-prefix',
            '--iri-prefix',
            nargs=2,
            metavar=('DIRECTORY', 'URI_PREFIX'),
            action='append',
            dest='prefixes',
            help="A directory followed by a URI prefix that MUST have a path "
                 "ending in '/'; all files loaded from this directory with "
                 "the '-f' option without specifying a URI will be assigned "
                 "URIs by replacing the directory with the URI prefix and "
                 "removing any file extension suffix (e.g. '.json', '.yaml')"
        )
        parser.add_argument(
            '-D',
            '--directory',
            nargs='+',
            action='append',
            dest='directories',
            help="A directory containing API description files, optionally "
                 "followed by an URI prefix with a path component ending in "
                 "a '/';  All files with a .json, .yaml, or .yml anywhere "
                 "under the directory will be loaded; if an URI prefix is "
                 "provided, the file path relative to the directory, but "
                 "without the file extension, will be appended to the prefix "
                 "to determine each file's URI; otherwise, each file will be "
                 "assigned its corresponding 'file:' URI.\n\n"
                 "See below for scenarios where certain files must be "
                 "loaded separately with -f and -d.",
        )
        parser.add_argument(
            '-i',
            '--allow-iris',
            action='store_true',
            help="Allow IRIs (URIs/URLs with full unicode support) even where "
                 "OAS and JSON Schema only support URIs/URLs; only use this "
                 "option if your OAS tooling supports IRIs and you want to "
                 "suppress errors about using unencoded non-ASCII characters "
                 "in your URIs/URLs."
        )
        parser.add_argument(
            '-n',
            '--no-source-map',
            action='store_true',
            help="Disable line number tracking for API descriptions, which "
                 "substantially improves performance; locations wills be "
                 "reported using JSON Pointers only; Note that currently, the "
                 "YAML line map package sometimes gets confused and drops "
                 "the line numbers anyway (this will be fied at some point).",
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
            '-t',
            '--store',
            default='none',
            choices=(('none',)),
            help="TODO: Support storing to various kinds of databases."
        )
        parser.add_argument(
            '--test-mode',
            action='store_true',
            help="Omit data such as 'locatedAt' that will change for "
                 "every environment.  This is intended to facilitate "
                 "automated testing of the entire system.",
        )
        args = parser.parse_args()
        if args.directories:
            raise NotImplementedError('-D option not yet implemented')

        prefixes = [cls._process_prefix(p) for p in args.prefixes] \
            if args.prefixes \
            else []
        # Reverse sort so that the first matching prefix is the longest
        prefixes.sort(reverse=True)

        resources = [cls._process_resource_arg(
            r,
            prefixes,
            not args.no_source_map,
        ) for r in args.files]

        candidates = list(filter(lambda r: 'openapi' in r['data'], resources))
        if not candidates:
            logger.error("No document contains an 'openapi' field!")
            return -1
        if len(candidates) > 1:
            logger.error(
                "Multiple documents with an 'openapi' field "
                "not yet supported"
            )
            return -1
        primary = candidates[0]

        desc = ApiDescription(
            primary['data'],
            primary['uri'],
            path=primary['path'],
            sourcemap=primary['sourcemap'],
            test_mode=args.test_mode,
        )
        for r in resources:
            if r['uri'] != primary['uri']:
                desc.add_resource(
                    r['data'],
                    r['uri'],
                    path=r['path'],
                    sourcemap=r['sourcemap'],
                )
            logger.info(f"Adding document {r['path']!r} <{r['uri']}>")

        desc.validate()
        if args.output_format is not None or args.test_mode is True:
            desc.serialize(output_format=args.output_format)
        else:
            print('Your API description is valid!')
