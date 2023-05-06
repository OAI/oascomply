import argparse
import json
from pathlib import Path
from uuid import uuid4
from collections import namedtuple
from typing import Any, Optional, Tuple

from jschon import (
    create_catalog, JSON, JSONSchema, URI,
    JSONPointer, JSONPointerError,
    RelativeJSONPointer, RelativeJSONPointerError,
)
import rdflib
from rdflib.namespace import RDF
import rfc3987
import yaml
import json_source_map as jmap
import yaml_source_map as ymap

__all__ = [
    'ApiDescription',
    'SchemaParser',
]


UriPrefix = namedtuple('UriPrefix', ['prefix', 'dir'])


class ApiDescription:
    """
    Representation of a complete API description.

    The constructor arguments are used to load the primary API description
    resource.  This resource MUST contain an ``openapi`` field setting
    the version.  Currently, 3.0.x descriptions are supported, with 3.1.x
    support intended for a later version.

    :param url:  See ``url`` param of :meth:`add_resource`
    :param uri:  See ``uri`` param of :meth:`add_resource`
    :param data_string:  See ``data_string`` param of :meth:`add_resource`
    :param data_format:  See ``data_format`` param of :meth:`add_resource`
    :param data_content: See ``data_content`` param of :meth:`add_resource`
    """
    FORMAT_JSON = 'JSON'
    """Constant for the JSON data format"""

    FORMAT_YAML = 'YAML'
    """Constant for the YAML data format"""

    CONTENT_OAS = 'openapi'
    CONTENT_JSON_SCHEMA = 'schema'

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        uri: Optional[str] = None,
        data_string: Optional[str] = None,
        data_format: str = FORMAT_YAML,
        data_content: str = CONTENT_OAS,
    ) -> None:
        self._contents = {}
        self._locations = {}

        primary, self._primary_uri = self.add_resource(
            contents=contents,
            url=url,
            uri=uri,
            data_format=data_format,
            _primary=True,
        )
        self._version = primary['openapi']

    def add_resource(
        self,
        *,
        contents: Optional[str] = None,
        url: Optional[str] = None,
        uri: Optional[str] = None,
        data_format: str = FORMAT_YAML,
        data_content: str = CONTENT_OAS,
        _primary: bool = False,
    ) -> Tuple[Any, str]:
        """
        Add a resource as part of the API description, and set its URI
        for use in resolving references and in the parser's output.

        The resource must be supplied either as a string via ``contents``,
        in which case it will be parsed according to ``data_format``,
        or through a loadable ``url``.   This ensures that line numbers
        can be reported property.  If a URL is provide, the retrieved
        resource will be parsed according to:

        1.  Retrieval metadata such as HTTP ``Content-Type``, or...
        2.  A ``.json`` or ``.yaml`` file extension, or...
        3.  The ``data_format`` parameter, which defaults to JSON and
            can be set using the ``FORMAT_*`` constants that are part
            of this class.

        Curently only ``file:`` URLs are supported.  Note that security
        settings in the OAS compliance suite configuration may need to
        be adjusted to allow filesystem access.

        The parsed resource will be stored in a cache under its URI
        for access
        when resolving references.
        The resource's URI is determined by the first usable option
        in the following list:

        1.  URI defined within the resource content (e.g. JSON Schema's
            ``$id`` keyword, or a ``self`` link in HTML)
        2.  The ``uri`` parameter
        3.  The ``url`` parameter
        4.  An automatically generated ``urn:uuid:`` URI

        Note that relying on an automatically generated URI is only really
        useful if the description only involves a single resource.  Otherwise,
        the output becomes difficult to understand.

        If the determined URI is a relative reference, it is resolved against
        a base URI as defined by the remaining steps, except for step 4.
        For a base URI, instead of generating a ``urn::uuid:`` URI, the
        ``file:`` URI of the compliance parser script is used.

        1.  If the resource is in a format that can declare its own
            URI, such as ``application/schema+json`` or ``text/html``,
            and such a declaration is present, that declaration is used.

            In the case of JSON Schema draft 2020-12 resource, or OAS 3.1
            Schema Objects, embedded ``$id`` keywords are detected and
            treated as separate resources in accordance with the JSON Schema
            specification.

            If the in-content URI is a relative reference, the the base
            URI is determined according to the remaining steps in this process.

        2.  If the ``uri`` parameter is present, it is used.

        3.  If the ``url`` parameteris present, it is used

        :param url: The URL from which the resource may be loaded.
            Currently only ``file:`` URLs are supported.
        :param uri: The identifier for this resource, as used in absolute
            references and to be displayed in output.
        :param data_string: A string representation of the resource.  Either
            ``data_string`` or ``url`` MUST be passed.
        :param data_format: The format (JSON or YAML) of the data.  Defaults
            to :attr:`ApiDescription.FORMAT_YAML`
        :param data_content: The type of content (OpenAPI or JSON Schema);
            note that OAS 3.0 schemas are considered OpenAPI content.  Only
            OAS 3.1 schema documents are considered JSON Schema.  This, along
            with the OAS version for OAS documents, is used to determine
            whether and how to detect URIs within the content.  Defaults to
            :attr:`ApiDescription.CONTENT_OAS`.
        """
        resolved_uri = uri
        if url:
            parsed = rfc3987.parse(url, rule='IRI')
            if parsed['scheme'] != 'file':
                raise ValueError(f"Cannot load non-file URL {url!r}")
            if parsed['authority'] and parsed['authority'] != 'localhost':
                raise ValueError(f"Cannot load non-local file URL {url!r}")
            with open(parsed['path']) as data_fd:
                if data_format == self.FORMAT_YAML:
                    data = yaml.safe_load(data_fd)
                elif data_format == self.FORMAT_JSON:
                    data = json.load(data_fd)
                else:
                    raise ValueError(f"Unsupported format {data_format!r}")
            if not resolved_uri:
                resolved_uri = url
        if not resolved_uri:
            resolved_uri = f'urn:uuid:{uuid4()}'

        if (
            (_primary and data['openapi'].startswith('3.1')) or
            self._version.startswith('3.1')
        ):
            # TODO: "$id" support for OAS 3.1
            raise ValueError('OAS 3.1 not yet supported.')

        self._contents[resolved_uri] = data
        self._locations[resolved_uri] = {
            'url': url,
            'line_map': None, # TBD, probably construct-on-demand?
        }
        return data, resolved_uri

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

    @classmethod
    def _process_resource_arg(cls, r, prefixes):
        if isinstance(r, str):
            path = Path(r)
            full_path = path.resolve()
            uri = full_path.as_uri()
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
            'path': str(path),
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

        for r in resources:
            print(f"{r['path']!r}: <{r['uri']}>")