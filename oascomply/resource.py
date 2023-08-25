from __future__ import annotations

import logging
from collections import defaultdict
from functools import cached_property
from pathlib import Path
from typing import (
    Any, ClassVar, Dict, Literal, Mapping, Optional,
    Sequence, Tuple, Type, Union,
)

import jschon
import jschon.exc
from jschon.jsonformat import JSONFormat
from jschon.resource import JSONResource
from jschon.catalog import Source
from jschon.vocabulary import Metaschema

import oascomply
from oascomply.oassource import (
    OASSource, DirectMapSource, FileMultiSuffixSource, HttpMultiSuffixSource,
)
from oascomply.oas3dialect import (
    OAS30_DIALECT_METASCHEMA,
    OAS30_VOCAB_LIST,
    OAS30_SUBSET_VOCAB,
    OAS30_SCHEMA,
    OAS30_SCHEMA_PATH,
    OAS31_DIALECT_METASCHEMA,
    OAS31_VOCAB_LIST,
    OAS31_SCHEMA,
    OAS31_SCHEMA_PATH,
)


__all__ = [
    'OASNodeBase',
    'OASNode',
    'OASContainer',
    'OASDocument',
    'OASFormat',
    'OASFragment',
    'OASResourceManager',
    'OASType',
    'URI',
    'URIError',
    'ThingToURI',
    'PathToURI',
    'URLToURI',
    'OAS_SCHEMA_INFO',
]


logger = logging.getLogger(__name__)


# TODO: Sort out vs oascomply.oas3dialect and oascomply.patch
OAS_SCHEMA_INFO = {
    '3.0':  {
        'schema': {
            'uri': OAS30_SCHEMA,
            'path': OAS30_SCHEMA_PATH,
            'vocabs': OAS30_VOCAB_LIST,
        },
        'dialect': {
            # We don't need a path as loading this dialect is managed by
            # the oascomply.oas3dialect module.
            'uri': OAS30_DIALECT_METASCHEMA,
            'vocab-meta': {},
        },
    },
    '3.1': {
        'schema': {
            'uri': OAS31_SCHEMA,
            'path': OAS31_SCHEMA_PATH,
            'vocabs': OAS31_VOCAB_LIST,
        },
        'dialect': {
            # We don't need a path as loading this dialect is managed by
            # the oascomply.oas3dialect module.
            'uri': OAS31_DIALECT_METASCHEMA,
            'vocab-meta': {},
        },
    },
}


URI: TypeAlias = jschon.URI
"""URI alias for modules that otherwise have no need for jschon."""


URIError: TypeAlias = jschon.exc.URIError
"""URI error alias for modules that otherwise have no need for jschon."""


# TODO: Is this in the right module?
OASType: TypeAlias = str
"""Alias indicating that the string is an OAS semantic type name."""


OASVersion: TypeAlias = Literal['3.0', '3.1']
"""Alias limiting the OAS version to only supported X.Y version strings."""


class ThingToURI:
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

            self._auto_uri = len(values) == 1
            self._values = values
            self._to_strip = strip_suffixes
            self._uri_is_prefix = uri_is_prefix

            thing = self._set_thing(values[0])
            if len(values) == 2:
                uri_str = values[1]
                logger.debug(
                    f'Using URI <{uri_str}> from command line for "{thing}"'
                )
            else:
                uri_str = self._uri_str_from_thing(
                    self._strip_suffixes(thing),
                )
                logger.debug(
                    f'Calculated URI <{uri_str}> for "{thing}"'
                )

            uri_obj = URI(uri_str)
            if uri_is_prefix and not uri_obj.path.endswith('/'):
                raise ValueError(
                    f"URI prefix <{uri_str}> must have a path ending in '/'",
                )

            self.set_uri(uri_str)

            if uri_is_prefix and uri_obj.query or self.uri.fragment:
                raise ValueError(
                    f"URI prefix <{self.uri}> may not include "
                    "a query or fragment",
                )

            logger.info(f'Constructed ThingToURI {self})')

        except Exception:
            # argparse suppresses any exceptions that are raised, so log them
            import traceback
            from io import StringIO

            buffer = StringIO()
            traceback.print_exc(file=buffer)
            logger.warning(buffer.getvalue())

            raise

    def __repr__(self):
        return (
            f'{self.__class__.__name__}('
            f'{self._values!r}, {self._to_strip!r}, {self._uri_is_prefix})'
        )

    def __eq__(self, other):
        if not isinstance(other, ThingToURI):
            return NotImplemented
        return self.thing == other.thing and self.uri == other.uri

    @property
    def thing(self):
        """
        Generic thing accessor; subclasses should offer a more specific one.

        See non-public :meth:`_set_thing` for modifications.
        """
        return self._thing

    @property
    def auto_uri(self) -> bool:
        """
        True if this class generated a URI rather than receivingit as a param.
        """
        return self._auto_uri

    def __str__(self):
        return f'(thing: {self._values[0]}, uri: <{self.uri}>)'

    def _strip_suffixes(self, thing: Any) -> str:
        thing_string = str(thing)
        for suffix in self._to_strip:
            if thing_string.endswith(suffix):
                return thing_string[:-len(suffix)]
        return thing_string

    def _set_thing(self, thing_str) -> Any:
        self._thing = thing_str
        return thing_str

    def set_uri(
        self,
        uri_str: str,
        attrname: str = 'uri',
    ) -> None:
        uri = URI(uri_str)
        try:
            uri.validate(require_scheme=True)
            setattr(self, attrname, (uri))
        except URIError as e:
            logger.debug(
                f'got exception from URI ({uri_str}):'
                f'\n\t{e}'
            )
            raise ValueError(f'{uri_str} cannot be relative')

    def _uri_str_from_thing(self, stripped_thing_str: str) -> str:
        return stripped_thing_str


class PathToURI(ThingToURI):
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

    def _uri_str_from_thing(self, stripped_thing_str: str) -> str:
        # It seems odd to rebuild the path object, but Path.with_suffix('')
        # doesn't care what suffix is removed, so we couldn't use it anyway
        # Also, arg parsing code does not need to be blazingly fast.
        path = Path(stripped_thing_str).resolve()

        # Technically, URI trailing slashes don't mean the same thing as
        # "directory", but that is the expectation of the dir mapping code.
        uri = path.as_uri()
        if path.is_dir() and self._uri_is_prefix and not uri.endswith('/'):
            uri += '/'

        return uri

    @property
    def path(self) -> Path:
        """Accessor for ``path``, the "thing" of this ThingToURI subclass."""
        return self._path

    @path.setter
    def path(self, p: Path) -> None:
        self._path = p

    @property
    def thing(self) -> Any:
        return self.path


class URLToURI(ThingToURI):
    """URL to URI utility class; does not check URL scheme or usability."""
    def __str__(self):
        return f'(url: <{self.url}>, uri: <{self.uri}>)'

    def _set_thing(self, thing_str: str) -> None:
        self.set_uri(thing_str, attrname='url')
        if self._uri_is_prefix and not self.url.path.endswith('/'):
            raise ValueError(
                f"URL prefix <{thing_str}> must have a path ending in '/'",
            )
        return self.url

    @property
    def url(self) -> URI:
        """Accessor for ``url``, the "thing" of this ThingToURI subclass."""
        return self._url

    @url.setter
    def url(self, u: URI) -> None:
        self._url = u

    @property
    def thing(self):
        return self.url


class OASNodeBase:
    """
    Mixin base interface and implementation across all OAS node types.

    All nodes in an OAS document need to know their :attr:`oasversion`,
    but otherwise the hierarchy is not unified.

    In the :class:`jschon.json.JSON` hierarchy:

    * :class:`jschon.resource.JSONResource` adds URI identification plus
      support for referencing other resources and being loaded through
      a :class:`jschon.catalog.Catalog` instance (which for ``oascomply``
      is wrapped by :class:`OASResourceManager`); all OAS document nodes
      should subclass :class:`~jschon.resource.JSONResource`
    * :class:`jschon.jsonformat.JSONFormat` requires a metadocument
      against which the format can be validated; only OAS document nodes
      that know their :class:`OASType`, either implicitly by being
      a complete document or explicitly due to being referenced in a way
      that requires a specific :class:`OASType`, can support this
    * :class:`jschon.jsonschema.JSONSchema`, of course, adds JSON Schema
      support, which is only relevant to the Schema Object within OAS

    Each of the above classes provides ways to access parent (and in some
    cases child) nodes that are witihn the same format or resource.  This
    is critical for OAS 3.1 support, as crossing a format boundary changes
    the metadocument, while crossing a resource boundary changes the base URI
    used for referencing, specifically ``"$ref"``, ``"operationRef"``, and
    the initial resolution of ``"$dynamicRef"``.

    OAS 3.1 Schema Objects that contain the ``"$id"`` keyword are separate
    *resources*, inside which relative references are resolved against the
    value of `"$id"` (which is itself resolved against it's parent resource's
    base URI if necessary).  The ``"$anchor"`` and ``"$dynamicAnchor``
    keywords create plain-name URI fragments within the resource (not globally).

    OAS 3.x Schema Objects are also a separate *format* from the rest of the
    OAS document.  In OAS 3.0, this is mostly a philosophical distinction as
    the Schema Object's metaschema (which is its metadocument) cannot change
    and is incorporated into the overall OAS schema (which is the OAS format
    metadocument).  This makes it possible to use the same metadocument for
    all of an OAS 3.0 document, including the Schema Objects.

    OAS 3.1 Schema Objects are more complex, as their metadocument is
    determined by the OpenAPI Object's ``jsonSchemaDialect`` field.
    As they fully support JSON Schema draft 2020-12, Schema Objects with
    an ``"$id"`` can *also* have ``"$schema"``, which can change the
    metaschema to something different from what the ``jsonSchemaDialect``
    defines.

    In the following hierarchy diagram, classes marked with a "*" extend
    this base as well as the appropriate base from the
    :class:`~jschon.json.JSON` hierarchy, and can be instantiated by
    :meth:`oas_factory` through a :class:`OASResourceManager`.

    ::

        jschon.JSON
        |- jschon.resource.JSONResource
           |- OASNode*
           |- OASContainer*
           |- jschon.jsonformat.JSONFormat
              |- OASFormat*
                |- OASDocument
                |- OASFragment
              |- jschon.JSONSchema
                |- OASSchema*

    Treating this class (:class:`OASNodeBase`) as a mixin rather than also
    extending :class:`~jschon.resource.JSONResource` avoids the confusion
    common with "diamond-shaped" mutiple inheritance.
    """
    @classmethod
    def oas_factory(
        cls,
        value,
        *args,
        catalog: Union[str, jschon.Catalog] = 'oascomply',
        uri: Optional[URI] = None,
        oasversion: Optional[OASVersion] = None,
        oastype: OASType = 'OpenAPI',
        **kwargs,
    ) -> OASNodeBase:

        if uri is not None and uri.fragment and uri.fragment.startswith('/'):
            pointer = jschon.JSONPointer.parse_uri_fragment(uri.fragment)
            if oastype == 'OpenAPI':
                kwargs['oas_document_pointers'] = [pointer]
            else:
                kwargs['oas_fragment_pointers'] = {pointer: oastype}

            return OASContainer(
                value,
                *args,
                uri=uri,
                catalog=catalog,
                oasversion=oasversion,
                oas_document_pointers=oas_document_pointers,
                oas_fragment_pointers=oas_fragment_pointers,
                **kwwrgs,
            )

        if 'openapi' in value:
            if oastype != 'OpenAPI':
                raise ValueError(
                    f"OAS type {oastype!r} requested for full "
                    f"OAS document <{uri}>",
                )
            return OASDocument(
                value,
                *args,
                uri=uri,
                catalog=catalog,
                oasversion=oasversion,
                **kwargs,
            )
        if oastype == 'OpenAPI':
            raise ValueError(
                f"Full OAS document requested for <{uri}> but "
                "no 'openapi' field present.",
            )

        return OASFragment(
            value,
            *args,
            uri=uri,
            catalog=catalog,
            oasversion=oasversion,
            oastype=oastype,
            **kwargs,
        )

    @property
    def oasversion(self):
        return self._oasversion

    def _set_oasversion(
        self,
        *,
        uri: URI,
        parent: Optional[jschon.JSON],
        from_params=None,
        from_value=None,
    ):
        if (from_params, from_value) == (None, None):
            if parent is not None and isinstance(parent, OASFormat):
                self._oasversion = parent.oasversion
                return

            raise ValueError(
                f"No OAS version provided or found for <{uri}>",
            )

        if from_value is not None:
            from_value = from_value[:from_value.rindex('.')]

        if (
            from_params is not None and from_value is not None and
            from_params != from_value
        ):
            raise ValueError(
                f"Expected OAS version {from_params!r} but found "
                f"version {from_value!r} in <{uri}>",
            )

        # It does not matter which it is from at this point
        ov = from_params if from_params else from_params
        if from_params:
            self._oasversion = from_params
        else:
            self._oasversion = from_value

        if (
            parent is not None and
            isinstance(parent, OASFormat) and
            self._oasversion != parent.oasversion
        ):
            raise ValueError(
                f"OAS version {self._oasversion!r} for <{uri}> conflicts "
                f"with parent <{parent.pointer_uri}>",
            )

        if self._oasversion not in OAS_SCHEMA_INFO:
            raise ValueError(f"Unknown OAS version {self.oasversion!r}")


class OASNode(JSONResource, OASNodeBase):
    """Node in an OAS doc that is not aware of its OAS type or metadocument"""
    def __init__(
        self,
        *args,
        oasversion: Optional[str] = None,
        uri: Optional[URI] = None,
        parent: Optional[jschon.JSON] = None,
        catalog: Union[str, jschon.Catalog] = 'oascomply',
        **kwargs,
    ):
        if parent is None:
            raise ValueError(
                "Class OASNode cannot be a document root (without a parent)",
            )
        logger.info(
            f'Creating new {type(self).__name__} ({id(self)}), '
            f'provided uri <{kwargs.get("uri")}>',
        )

        # TODO: refactor some of this duplication
        self._set_oasversion(
            uri=uri,
            parent=parent,
            from_params=oasversion,
        )

        super().__init__(
            *args,
            uri=uri,
            parent=parent,
            catalog=catalog,
            oasversion=self.oasversion,
            **kwargs,
        )

        logger.info(
            f'New {type(self).__name__} ({id(self)}) created: '
            f'<{self.pointer_uri}>',
        )

    @cached_property
    def containing_format_root(self):
        current = self
        while (p := current.parent) is not None:
            if isinstance(p, OASFormat):
                return p.format_root
            current = p
        return None

    @property
    def sourcemap(self):
        return self.containing_format_root.sourcemap

    @property
    def url(self):
        return self.resource_root.url.copy(
            fragment=self.pointer_uri.fragment,
        )


class OASFormat(JSONFormat, OASNodeBase):
    """Base for all OAS document nodes."""
    _default_metadocument_cls = Metaschema

    def __init__(self, *args, uri, catalog='oascomply', **kwargs):
        try:
            v = self._oasversion
        except AttributeError:
            v = None
        if v is None:
            raise TypeError(
                'OASFormat should only be instantiated through a subclass.'
            )
        logger.info(f'Creating new {type(self).__name__} ({id(self)})...')
        logger.info(f'...provided node uri <{kwargs.get("uri")}>')
        logger.info(f'...provided meta uri <{kwargs.get("metadocument_uri")}>')

        self._sourcemap = None
        self._url = None

        if 'itemclass' not in kwargs:
            kwargs['itemclass'] = OASNode

        super().__init__(
            *args,
            uri=uri,
            catalog=catalog,
            **kwargs)

        logger.info(
            f'New {type(self).__name__} ({id(self)}) created: '
            f'<{self.pointer_uri}>...',
        )
        logger.info(f'...metadocument <{self.metadocument_uri}>')

    def is_format_root(self) -> bool:
        return self.parent is None or not isinstance(self.parent, OASFormat)

    @cached_property
    def format_parent(self) -> Optional[OASFormat]:
        """All OASFormat subclasses are considered the same format."""
        candidate = None
        current = self

        while (candidate := current.parent) is not None:
            if isinstance(candidate, OASFormat):
                return candidate
            current = candidate
        return candidate

    # TODO: should URLs only be document-scope? resource-scope?
    #       URLs for embedded resources would be document root-relative...
    #       Should the document root URL have an empty fragment or no fragment?
    @property
    def url(self):
        return self._url

    @url.setter
    def url(self, url):
        self._url = url

    @property
    def sourcemap(self):
        return self._sourcemap

    @sourcemap.setter
    def sourcemap(self, sourcemap):
        self._sourcemap = sourcemap

    # TODO: Should only OASDocument have this?
    #       If so, where does OASFragment's schema fragment go?
    def _get_oas_schema_uri(
        self,
        *,
        uri: URI,
        from_params: Optional[URI] = None,
        from_oastype: Optional[URI] = None,
    ):
        from_oasversion = URI(
            OAS_SCHEMA_INFO[self.oasversion]['schema']['uri']
        )
        logger.debug(
            f'OAS metadocument candidates for <{uri}> ({id(self)}):\n'
            f'\t\tfrom params:     <{from_params}>\n'
            f'\t\tfrom oastype:    <{from_oastype}>\n'
            f'\t\tfrom oasversion: <{from_oasversion}>',
        )
        if (from_params, from_oastype) == (None, None):
            logger.debug(
                f'Selected metadocument <{from_oasversion}> '
                f'for <{uri}> ({id(self)})',
            )
            return from_oasversion

        bases = {from_oasversion}
        with_fragment = set()
        if from_params:
            bases.add(from_params.copy(fragment=None))
            if from_params.fragment:
                with_fragment.add(from_params)
        if from_oastype:
            bases.add(from_oastype.copy(fragment=None))
            if from_oastype.fragment:
                with_fragment.add(from_oastype)

        if len(bases) > 1 or len(with_fragment) > 1:
            raise ValueError(
                f"Conflicting metadocument URIs for <{uri}>:\n"
                f"\tfrom oasversion: <{from_oasversion}>\n"
                f"\tfrom parameters: <{from_params}>\n"
                f"\tfrom oastype:    <{from_oastype}>",
            )

        selected = with_fragment.pop() if with_fragment else from_oasversion
        logger.debug(
            f'Selected metadocument <{selected}> for <{uri}> ({id(self)})',
        )
        return selected.copy()


class OASDocument(OASFormat):
    """
    A class for the root node of a proper OAS document.

    This means an OAS data structure with an "openapi" field at the root.
    The structure can be embedded in a larger non-OAS document.
    """
    def __init__(
        self,
        value,
        *args,
        uri: Optional[URI] = None,
        parent: Optional[jschon.JSON] = None,
        metadocument_uri: Optional[URI] = None,
        oasversion: Optional[str] = None,
        **kwargs,
    ):
        if parent is None and uri is None:
            raise ValueError(
                'The "uri" parameter is required for OASDocument nodes '
                'that are overall document root nodes (without a parent)',
            )

        if 'openapi' not in value:
            raise ValueError(
                "Expected an 'openapi' field in <{uri}> but none found"
            )

        self._set_oasversion(
            uri=uri,
            parent=parent,
            from_value=value['openapi'],
            from_params=oasversion,
        )
        metadocument_uri = self._get_oas_schema_uri(
            uri=uri,
            from_params=metadocument_uri,
        )

        super().__init__(
            value,
            *args,
            uri=uri,
            parent=parent,
            metadocument_uri=metadocument_uri,
            oasversion=self.oasversion,
            **kwargs,
        )


class OASFragment(OASFormat):
    def __init__(
        self,
        *args,
        oastype: str,
        oasversion: Optional[str] = None,
        uri: Optional[URI] = None,
        parent: Optional[jschon.JSON] = None,
        metadocument_uri: Optional[URI] = None,
        **kwargs,
    ):
        if parent is None and uri is None:
            raise ValueError(
                'The "uri" parameter is required for OASFragment nodes '
                'that are overall document root nodes (without a parent)',
            )

        self._set_oasversion(
            uri=uri,
            parent=parent,
            from_params=oasversion,
        )
        oas_schema_uri = URI(
            OAS_SCHEMA_INFO[self.oasversion]['schema']['uri']
        )

        if self.oasversion == '3.0':
            from_oastype = oas_schema_uri.copy(fragment=f'/$defs/{oastype}')
        elif self.oasversion == '3.1':
            kebab_name = []
            for char in oastype:
                if char.isupper() and kebab_name:
                    kebab_name.append('-')
                kebab_name.append(char.lower())
            from_oastype = oas_schema_uri.copy(
                fragment=f'/$defs/{"".join(kebab_name)}',
            )

        metadocument_uri = self._get_oas_schema_uri(
            uri=uri,
            from_params=metadocument_uri,
            from_oastype=from_oastype,
        )
        super().__init__(
            *args,
            uri=uri,
            parent=parent,
            metadocument_uri=metadocument_uri,
            oasversion=self.oasversion,
            **kwargs,
        )


class OASContainer(JSONResource, OASNodeBase):
    """Non-OAS document node with at least one OASFormat descendant"""
    def __init__(
        self,
        *args,
        oas_fragment_pointers: Optional[
            Mapping[jschon.JSONPointer, OASType]
        ] = None,
        oas_document_pointers: Sequence[jschon.JSONPointer] = (),
        **kwargs,
    ):
        if (oas_fragment_pointers, oas_document_pointers) == ((), ()):
            raise ValueError(
                "OASContainer expects at least one of 'oas_fragment_pointers' "
                "or 'oas_document_pointers' to be non-empty",
            )
        logger.info(
            f'Creating new {type(self).__name__} ({id(self)}), '
            f'provided uri <{kwargs.get("uri")}>',
        )

        if oas_fragment_pointers is None:
            oas_fragment_pointers = {}

        self._fragment_fields = {}
        child_fragment_pointers = {}

        for p, t in oas_fragment_pointers.items():
            if len(p) == 1:
                self._fragment_fields[p[0]] = t
            elif len(p) > 1:
                child_fragment_pointers[p[1:]] = t

        self._document_fields = []
        child_document_pointers = []

        for p in oas_document_pointers:
            if len(p) == 1:
                self._document_fields.append(p[0])
            elif len(p) > 1:
                child_document_pointers.append(p[1:])
            else:
                raise ValueError(
                    f'OASContainer OASDocument pointer {p} must have '
                    'at least one component'
                )

        if 'itemclass' not in kwargs:
            kwargs['itemclass'] = OASContainer

        # the oas pointers will get passed through itemkwargs
        kwargs['oas_document_pointers'] = child_document_pointers
        kwargs['oas_fragment_pointers'] = child_fragment_pointers

        super.__init__(*args, **kwargs)

        logger.info(
            f'New {type(self).__name__} ({id(self)}) created: '
            f'<{self.pointer_uri}>',
        )

    def instantiate_sequence(self, value):
        seq = []
        newkwargs = {
            k: v for k, v in self.itemkwargs.items()
            if k not in ('child_document_pointers', 'child_fragment_pointers')
        }
        for i, v in enumerate(value):
            si = str(i)
            if si in self._fragment_fields:
                seq.append(OASFragment(
                    v,
                    oastype=self._fragment_fields[si],
                    parent=self,
                    key=si,
                    **newkwargs,
                ))
            elif si in self._document_fields:
                seq.append(OASDocument(v, parent=self, key=si, **newkwargs))
            else:
                seq.append(
                    self.itemclass(v, parent=self, key=si, **self.itemkwargs),
                )

        return seq

    def instantiate_mapping(self, value):
        mapping = {}
        newkwargs = {
            k: v for k, v in self.itemkwargs.items()
            if k not in ('child_document_pointers', 'child_fragment_pointers')
        }
        for k, v in value.items():
            if k in self._fragment_fields:
                mapping[k] = OASFragment(
                    v,
                    oastype=self._fragment_fields[k],
                    parent=self,
                    key=k,
                    **newkwargs,
                )
            elif k in self._document_fields:
                mapping[k] = OASDocument(v, parent=self, key=k, **newkwargs)
            else:
                mapping[k] = self.itemclass(
                    v, parent=self, key=k, **self.itemkwargs,
                )

        return mapping


class OASResourceManager:
    """
    Proxy for the jschon.Catalog, adding OAS-specific handling.

    This class manages the flow of extra information that
    :class:`jschon.catalog.Catalog` and :class:`jschon.catalog.Source` do not
    directly support.  This includes recording the URL from which a resource
    was loaded, as well as other metadata about its stored document form.
    """
    _direct_sources: ClassVar[
        Mapping[jschon.Catalog, DirectMapSource]
    ] = {}
    _url_maps: ClassVar[
        Mapping[jschon.Catalog, Mapping]
    ] = defaultdict(dict)
    _sourcemap_maps: ClassVar[
        Mapping[jschon.Catalog, Mapping]
    ] = defaultdict(dict)

    @classmethod
    def update_direct_mapping(
        cls,
        catalog: jschon.Catalog,
        mapping: Dict[URI, Union[Path, URI]],
    ):
        """
        Update the one no-prefix direct mapping source for the catalog.

        If no such :class:`DirectMapSource` exists, create one and register
        it with the catalog.

        Only one source can be (usefully) registered without a prefix, so all
        no-prefix mappings for a catalog need to go through the same map.
        """
        if (dm := cls._direct_sources.get(catalog)) is None:
            logger.debug(
                f'Initializing direct map source for {catalog} with {mapping}',
            )
            dm = DirectMapSource(mapping)
            cls.add_uri_source(catalog, None, dm)
            cls._direct_sources[catalog] = dm
        else:
            logger.debug(
                f'Updating direct map source for {catalog} with {mapping}',
            )
            dm.update_map(mapping)

    @classmethod
    def add_uri_source(
        cls,
        catalog: jschon.Catalog,
        base_uri: Optional[jschon.URI],
        source: Source,
    ) -> None:
        """
        Handle :class:`OASSource`-specific regisration aspects.

        This is a classmethod because sometimes a catalog must have
        sources added prior to knowing everything needed to construct
        an :class:`OASResourceManager` for it.  An example can be seen in
        ``oascomply/__init__.py`` by way of :meth:`update_direct_mapping`.
        """
        catalog.add_uri_source(base_uri, source)
        if isinstance(source, OASSource):
            # This "base URI" is really treated as a prefix, which
            # is why a value of '' works at all.
            source.set_uri_prefix(
                jschon.URI('') if base_uri is None else str(base_uri)
            )
            source.set_uri_url_map(cls._url_maps[catalog])
            source.set_uri_sourcemap_map(cls._sourcemap_maps[catalog])

    def __init__(
        self,
        catalog: jschon.Catalog,
        *,
        files: Sequence[PathToURI] = (),
        urls: Sequence[URLToURI] = (),
        directories: Sequence[PathToURI] = (),
        url_prefixes: Sequence[URLToURI] = (),
        dir_suffixes: Sequence[str] = (),
        url_suffixes: Sequence[str] = (),
    ) -> None:

        logger.debug(f"Initializing OASResourceManger for {catalog}")
        self._catalog = catalog
        self._uri_url_map = {}
        self._uri_sourcemap_map = {}
        self._adjusted_files: Sequence[PathToURI] = []
        self._adjusted_urls: Sequence[URLToURI] = []

        for dir_to_uri in directories:
            logger.debug(
                f'Mapping URI prefix <{dir_to_uri.uri}> '
                f'to path "{dir_to_uri.path}"',
            )
            self.add_uri_source(
                catalog,
                dir_to_uri.uri,
                FileMultiSuffixSource(
                    str(dir_to_uri.path), # TODO: fix type mismatch
                    suffixes=dir_suffixes,
                )
            )

        for url_to_uri in url_prefixes:
            logger.debug(
                f'Mapping URI prefix <{url_to_uri.uri}> '
                f'to URL prefix "{url_to_uri.url}"',
            )
            self.add_uri_source(
                catalog,
                url_to_uri.uri,
                HttpMultiSuffixSource(
                    str(url_to_uri.url),  # TODO: fix type mismatch
                    suffixes=url_suffixes,
                )
            )

        resource_map = {}
        for f_to_u in files:
            new_f_to_u, changed = self._match_prefix(
                f_to_u,
                directories,
                dir_suffixes,
            )
            if changed:
                self._adjusted_files.append(new_f_to_u)
                continue

            resource_map[f_to_u.uri] = f_to_u.path
            self._adjusted_files.append(f_to_u)

        for u_to_u in urls:
            new_u_to_u, changed = self._match_prefix(
                u_to_u,
                url_prefixes,
                url_suffixes,
            )
            if changed:
                self._adjusted_urls.append(new_u_to_u)
                continue

            resource_map[u_to_u.uri] = u_to_u.url
            self._adjusted_urls.append(u_to_u)

        if resource_map:
            self.update_direct_mapping(self._catalog, resource_map)

    def _match_prefix(
        self,
        a_thing: ThingToURI,
        prefix_things: Sequence[ThingToURI],
        suffixes: Sequence[str],
    ) -> Tuple[ThingToURI, bool]:
        if a_thing.auto_uri:
            a_str = str(a_thing.thing)

            for other_thing in sorted(
                prefix_things,
                key=lambda p: str(p.thing),
                reverse=True, # longest matches first
            ):
                other_str = str(other_thing.thing)

                if a_str.startswith(other_str):
                    if '.' in a_str and a_str[a_str.rindex('.'):] in suffixes:
                        a_str = a_str[:a_str.rindex('.')]
                        a_str = (
                            str(other_thing.uri) + a_str[len(other_str) + 1:]
                        )

                    logger.debug(
                        f'Re-assinging URI <{a_str}> to "{a_thing.thing}"',
                    )
                    return (
                        type(a_thing)([str(a_thing.thing), a_str], suffixes),
                        True,
                    )

        return (a_thing, False)

    def _get_with_url_and_sourcemap(
        self,
        uri,
        *,
        oasversion,
        oastype,
    ):
        base_uri = uri.copy(fragment=None)
        r = self._catalog.get_resource(
            uri,
            cacheid=oasversion,
            cls=OASNodeBase,
            factory=lambda *args, **kwargs: OASNodeBase.oas_factory(
                *args, oastype=oastype, oasversion=oasversion, **kwargs
            ),
        )

        if r.document_root.url is None:
            logger.debug(f'No URL for <{r.document_root.pointer_uri}>')
            logger.debug(f'URI <{uri}>; BASE URI <{base_uri}>')
            r.document_root.url = self.get_url(base_uri)
            r.document_root.source_map = self.get_sourcemap(base_uri)

        return r

    def get_entry_resource(
        self,
        initial: Optional[Union[URI, str]] = None,
        *,
        oasversion: Optional[OASVersion] = None,
    ) -> Optional[OASFormat]:
        uri = None
        if initial:
            uri = URI(initial) if isinstance(initial, str) else initial
        elif self._adjusted_files:
            uri = self._adjusted_files[0].uri
        elif self._adjusted_urls:
            uri = self._adjusted_urls[0].uri

        return None if uri is None else self.get_oas(uri, oasversion=oasversion)

    def get_oas(
        self,
        uri: jschon.URI,
        *,
        oasversion: Optional[str] = None,
        oastype: OASType = 'OpenAPI',
    ):
        oas_doc = self._get_with_url_and_sourcemap(
            uri,
            oasversion=oasversion,
            oastype=oastype,
        )
        return oas_doc

    def get_url(self, uri):
        try:
            return self._url_maps[self._catalog][uri]
        except KeyError:
            logger.error(
                f'could not find <{uri}> in {self._url_maps[self._catalog]}',
            )
            raise

    def get_sourcemap(self, uri):
        try:
            return self._sourcemap_maps[self._catalog][uri]
        except KeyError:
            logger.error(
                f'could not find <{uri}> in '
                f'{self._sourcemap_maps[self._catalog]}',
            )
            raise
