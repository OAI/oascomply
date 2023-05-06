import argparse
import json
from pathlib import Path
from uuid import uuid4
from collections import namedtuple
from typing import Any, Mapping, Optional, Tuple
import logging

import jschon

import rdflib
from rdflib.namespace import RDF
import rfc3987
import yaml
import json_source_map as jmap
import yaml_source_map as ymap

from oasparse.oasgraph import OasGraph
from oasparse.schemaparse import Annotation, SchemaParser

__all__ = [
    'ApiDescription',
]

logger = logging.getLogger(__name__)


UriPrefix = namedtuple('UriPrefix', ['prefix', 'dir'])


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
    ) -> None:
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

        self._g = OasGraph(
            self._version[:self._version.rindex('.')],
            base=uri,
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
            return self._contents[uri]
        except KeyError:
            absolute, fragment = urllib.parse.urldefrag(uri)
            try:
                data = self._contents[uri]
                return JSONPointer.parse_uri_fragment(fragment).evaluate(data)

            except (KeyError, JSONPointerError):
                return None

    def validate(self, resource_uri=None, oastype='OpenAPI'):
        sp = SchemaParser.get_parser(
            {},
            annotations=('oasType', 'oasChildren', 'oasReferences')
        )
        if resource_uri is None:
            assert oastype == 'OpenAPI'
            resource_uri = self._primary_uri

        data = self.get(resource_uri)
        output = sp.parse(data, oastype)
        to_validate = {}
        for unit in output['annotations']:
            ann=Annotation(unit, instance_base=resource_uri)
            method = f'add_{ann.keyword.lower()}'

            # Using a try/except here can result in confusion if something
            # else produces an AttributeError, so use hasattr()
            if hasattr(self._g, method):
                if resources := getattr(self._g, method)(ann, data):
                    for uri, oastype in resources:
                        to_validate[uri] = oastype
            else:
                raise ValueError(f"Unexpected annotation {ann.keyword!r}")
        self._validated.add(resource_uri)
        for uri, oastype in to_validate.items():
            if uri not in self._validated:
                self.validate(uri, oastype)

    @classmethod
    def _process_resource_arg(cls, r, prefixes):
        if isinstance(r, str):
            path = Path(r)
            full_path = path.resolve()
            uri = full_path.with_suffix('').as_uri()
            for p in prefixes:
                try:
                    rel = full_path.relative_to(p.dir)
                    uri = p.prefix + str(rel.with_suffix(''))
                except ValueError:
                    pass
        else:
            path = Path(r[0])
            uri = r[1]
        filetype = path.suffix[1:] or 'yaml'
        if filetype == 'yml':
            filetype = 'yaml'

        content = path.read_text()
        if filetype == 'json':
            data = json.loads(content)
            sourcemap = jmap.calculate(content)
        elif filetype == 'yaml':
            data = yaml.safe_load(content)
            sourcemap = ymap.calculate(content)
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
            parsed = rfc3987.parse(p[0], rule='IRI')
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
                rfc3987.parse(p[0], rule='IRI_reference')
                raise ValueError(f'URI prefixes cannot be relative: <{p[0]}>')
            except ValueError:
                raise ValueError(
                    f'URI prefix <{p[0]}> does not appear to be a URI'
                )

    @classmethod
    def load(cls):
        parser = argparse.ArgumentParser()
        parser.add_argument(
            '-o',
            '--oas-file',
            action='append',
            dest='resources',
            help="An API description file as a local file path, which will"
                 "appear in output as the corresponding 'file:' URL",
        )
        parser.add_argument(
            '-O',
            '--aliased-oas-file',
            nargs=2,
            action='append',
            dest='resources',
            help="An API description file path followed by the URI used "
                 "to identify it in references and output",
        )
        parser.add_argument(
            '-p',
            '--uri-prefix',
            nargs=2,
            action='append',
            dest='prefixes',
            help="A URI prefix, ending in a '/', followed by a filesystem "
                 "directory; all paths passed that are not already aliased "
                 "to a URI that are within the given directory will be "
                "assigned a URI constructed by replacing the directory with "
                "the prefix and removing any file extension (e.g. '.yaml' or "
                "'.json'); Note that 'file:' URIs are not allowed as prefixes "
                "as the default behavior is to use the appropriate 'file:' URI"
        )

        args = parser.parse_args()

        prefixes = [cls._process_prefix(p) for p in args.prefixes] \
            if args.prefixes \
            else []
        # Reverse sort so that the first matching prefix is the longest
        prefixes.sort(reverse=True)

        resources = [
            cls._process_resource_arg(r, prefixes) for r in args.resources
        ]

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
        print(desc._g.serialize())
