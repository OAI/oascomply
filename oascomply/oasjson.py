import re
import logging
import pathlib
from os import PathLike
from collections import defaultdict
from typing import Hashable, Mapping, Sequence, Type, Union

from jschon import JSON, JSONCompatible, JSONSchema, Result, URI
from jschon.exc import CatalogError
from jschon.catalog import Catalog, Source, LocalSource, RemoteSource
from jschon.jsonpointer import RelativeJSONPointer
from jschon.vocabulary.format import format_validator
from jschon.vocabulary import (
    Keyword, KeywordClass, Metaschema, ObjectOfSubschemas, Subschema,
    Vocabulary, format as format_, annotation, applicator, validation,
)

import rfc3339
import rfc3987

from oascomply.ptrtemplates import (
    JSON_POINTER_TEMPLATE, RELATIVE_JSON_POINTER_TEMPLATE,
    RelJsonPtrTemplate,
)
import oascomply.resourceid as rid

__all__ = [
    'OasCatalog',
    'OasJson',
    'OasJsonError',
    'OasJsonTypeError',
    'OasJsonUnresolvableRefError',
    'OasJsonRefSuffixError',
]

logger = logging.getLogger(__name__)


class UrlMappingSource(Source):
    @property
    def uri_url_map(self):
        """Return a shared map from requested URI to located URL"""
        return self._uri_url_map

    @uri_url_map.setter
    def uri_url_map(self, mapping: Mapping[str, str]):
        """Set a shared map from requested URI to located URL"""
        self._uri_url_map = mapping


class LocalMultiSuffixSource(UrlMappingSource):
    """
    Resource loader that searches for local files using a list of suffixes.

    :param base_dir: The directory in which to search for relative paths
    :param base_uri: The base URI / URI prefix under which this source
        will be registered with the :class:`OasCatalog`.  This MUST
        match the registered prefix so that mappings between resource
        URLs and URIs can be determined.
    :param suffixes: A list of suffixes, inlcuding the leading ``"."``,
        to try in order to find a match; the list MUST have at least one
        entry, but ``None`` is a valid entry for loading a non-suffixed file;
        the default is ``[".json", ".yaml"]``
        the resource was loaded, and the URI that was used to load it
    """
    def __init__(
        self,
        base_dir: Union[str, PathLike],
        *,
        base_uri: URI,
        suffixes: Sequence[Union[str, None]] = ['.json', '.yaml'],
        **kwargs,
    ) -> None:
        if 'suffix' in kwargs:
            raise ValueError("Cannot pass both 'suffix' and 'suffixes'")
        self._suffixes = tuple(suffixes)
        self._sources = [
            LocalSource(base_dir, suffix=s, **kwargs) for s in suffixes
        ]
        self._base_uri = base_uri

    def __call__(self, relative_path: str) -> JSONCompatible:
        for source in self._sources:
            try:
                resource = source(relative_path)
                uri = str(self._base_uri) + relative_path
                # LocalSource concatenates rather than using Path.with_suffix()
                if source.suffix:
                    relative_path += source.suffix
                url = str(
                    (pathlib.Path(source.base_dir) / relative_path).as_uri(),
                )
                # TODO: Normalize file:///?  Use rid.Iri?
                self.uri_url_map[uri] = url
                return resource

            except (OSError, CatalogError) as e:
                logger.debug(
                    f"Checked {self.base_dir!r} for {relative_path!r}, "
                    f"got exception:\n\t{e}"
                )
                pass

        raise CatalogError(
            f"Could not find source for {relative_path!r} with any of "
            f"suffixes {self._suffixes}",
        )


class RemoteMultiSuffixSource(Source):
    """
    Resource loader that searches for HTTPS resources using a list of suffixes.

    :param base_url: A base URL that is used as a prefix, and MUST end
        with a ``"/"`` so that base URL and URL prefix behavior matches
    :param base_uri: The base URI / URI prefix under which this source
        will be registered with the :class:`OasCatalog`.  This MUST
        match the registered prefix so that mappings between resource
        URLs and URIs can be determined.
    :param suffixes: A list of suffixes, inlcuding the leading ``"."``,
        to try in order to find a match; the list MUST have at least one
        entry, but ``None`` is a valid entry for loading a non-suffixed file;
        the default is ``[None, ".json", ".yaml"]``
    :param uri_url_map: A map from the URI used to request the resource
        to the URL from which the resource was loaded, which is expected
        to be shared among multiple source instances.
    """
    def __init__(
        self,
        base_url: URI,
        *,
        base_uri: URI,
        suffixes: Sequence[Union[str, None]] = [None, '.json', '.yaml'],
        uri_url_map: Mapping[str, str],
        **kwargs,
    ) -> None:
        if 'suffix' in kwargs:
            raise ValueError("Cannot pass both 'suffix' and 'suffixes'")
        self._base_uri = base_uri
        self._uri_url_map = uri_url_map
        raise NotImplementedError

    def __call__(self, relative_path: str) -> JSONCompatible:
        raise NotImplementedError


class OasCatalog(Catalog):
    @property
    def _uri_url_map(self):
        try:
            return self._u_u_map
        except AttributeError:
            self._u_u_map = []
            return self._u_u_map

    def get_resource(
        self,
        uri,
        *,
        resourceclass=None,
        metaschema_uri=None,
        cacheid='default',
    ):
        if resourceclass is None:
            resourceclass = OasJson

        try:
            logger.debug(
                f"Checking cache {cacheid} for resource '{uri}'",
            )
            return self._schema_cache[cacheid][uri]
        except KeyError:
            logger.debug(
                f"Resource '{uri}' not found in cache {cacheid}",
            )
            pass

        resource = None
        base_uri = uri.copy(fragment=False)

        if uri.fragment is not None:
            try:
                logger.debug(
                    f"Checking cache {cacheid} for base '{base_uri}'",
                )
                resource = self._schema_cache[cacheid][base_uri]
            except KeyError:
                pass

        if resource is None:
            logger.debug(f"Attempting to load '{base_uri}'")
            doc = self.load_json(base_uri)
            if oasv := doc.get('openapi'):
                if oasv.startswith('3.0'):
                    cacheid='3.0'
                elif oasv.startswith('3.1'):
                    cacheid='3.1'
                else:
                    raise ValueError(f'Unsupported OAS version {oasv!r}')
                logger.debug(f"Caching under OAS version {cacheid}")
            else:
                logger.debug(
                    f"No OAS version found, caching under {cacheid!r}",
                )

            url = self._uri_url_map[base_uri],
            logger.debug(f"Resolve URI '{base_uri}' via URL '{url}'")

            # TODO: oasversion kwarg?
            resource = resourceclass(
                doc,
                catalog=self,
                cacheid=cacheid,
                uri=base_uri,
                url=url,
                metaschema_uri=metaschema_uri,
            )
            try:
                logger.debug(f"Re-checking cache for '{uri}'")
                return self._schema_cache[cacheid][uri]
            except KeyError:
                logger.debug(
                    f"'{uri}' not in cache, checking JSON Pointer fragment",
                )

        if uri.fragment:
            try:
                ptr = rid.JsonPtr.parse_uri_fragment(uri.fragment)
                resource = ptr.evaluate(resource)
            except rid.JsonPtrError as e:
                raise CatalogError(f"Schema not found for {uri}") from e

        # TODO: Check OasJson-ness?
        return resource

    def add_uri_source(self, base_uri: URI, source: UrlMappingSource) -> None:
        source.uri_url_map = self._uri_url_map
        super().add_uri_source(base_uri, source)

    def get_schema(
            self,
            uri: URI,
            *,
            metaschema_uri: URI = None,
            cacheid: Hashable = 'default',
    ) -> JSONSchema:
        # TODO: metaschema_uri needs to be set based on oasversion
        #       This can be hard if loading a separate schema resource
        #       as we may not have access to the relevant "current"
        #       oasversion, which may change depending on the access
        #       path.  We may need separate 3.0 and 3.1 caches.
        try:
            return super().get_schema(
                uri,
                metaschema_uri=metaschema_uri,
                cacheid=cacheid,
            )
        except CatalogError as e:
            if 'not a JSON Schema' not in str(e):
                raise

            base_uri = uri.copy(fragment=False)
            resource = self.get_resource(base_uri, cacheid=cacheid)
            self.del_schema(uri)

            if uri.fragment is None or uri.fragment == '':
                self.del_schema(base_uri)
                # TODO: .value vs .data
                return OasJsonSchema(
                    resource.value,
                    uri=uri,
                    metaschema_uri=metaschema_uri,
                    catalog=self,
                    cacheid=cacheid,
                )
            if not uri.fragment.startswith('/'):
                raise ValueError(
                    'Non-JSON Pointer fragments not yet supported',
                )
            ptr = rid.JsonPtr.parse_uri_fragment(uri.fragment)
            parent_ptr = ptr[:-1]
            key = ptr[-1]

            parent = parent_ptr.evaluate(resource)
            return parent.convert_to_schema(key)


class OasJsonError(Exception):
    """Base class for errors raised by :class:`OasJson`"""
    def __str__(self):
        return self.args[0]


class OasJsonTypeError(OasJsonError, TypeError):
    """Indicates an attempt to treat an OasJson as a jschon.JSONSchema"""
    def __init__(self, uri, url):
        super().__init__('Cannot evaluate OasJson as JSONSchema', uri, url)

    @property
    def uri(self):
        """The URI of the mis-typed resource (possiby same as the URL)"""
        return self.args[1]

    @property
    def url(self):
        """The URL of the mis-typed resource"""
        return self.args[2]


class OasJsonUnresolvableRefError(OasJsonError, ValueError):
    """Indicates that a reference target could not be found."""
    def __init__(self, ref_uri):
        super().__init__(
            f"Could not resolve reference to {ref_uri}",
            ref_uri,
        )

    @property
    def ref_uri(self):
        return self.args[1]


class OasJsonRefSuffixError(OasJsonError, ValueError):
    """Indicates misuse of filesystem suffixes in retrieving a resource."""
    def __init__(
        self,
        source_schema_uri,
        ref_uri,
        ref_resource_uri,
        target_resource_uri,
        suffix,
    ):
        super().__init__(
            f"Reference without suffix attempted despite target resource "
            f"being registered under a URI with suffix",
            source_schema_uri,
            ref_uri,
            ref_resource_uri,
            target_resource_uri,
            suffix,
        )

    @property
    def source_schema_uri(self):
        return self.args[1]

    @property
    def ref_uri(self):
        return self.args[2]

    @property
    def ref_resource_uri(self):
        return self.args[3]

    @property
    def target_resource_uri(self):
        return self.args[4]

    @property
    def suffix(self):
        return self.args[5]


class OasJsonSchema(JSONSchema):
    """:class:`jschon.jsonschema.JSONSchema` subclass embeddable in :class:`OasJson`"""
    def __init__(
            self,
            value: Union[bool, Mapping[str, JSONCompatible]],
            *,
            catalog: Union[str, Catalog] = 'catalog',
            cacheid: Hashable = 'default',
            uri: URI = None,
            metaschema_uri: URI = None,
            parent: JSON = None,
            key: str = None,
            root: str = None,
    ):
        """
        All parameters the same as for :class:`jschon.jsonschema.JSONSchema` unless
        otherwise specified.

        :param root: The :class:`jschon.json.JSON` instance at the root of the document;
                     if None, then this instance is at the document root.  It is an error
                     to specify a parent but not a root.
        """
        super().__init__(
            value,
            catalog=catalog,
            cacheid=cacheid,
            uri=uri,
            metaschema_uri=metaschema_uri,
            parent=parent,
            key=key,
        )
        if root is None and parent is not None:
            raise ValueError('Cannot be a document root if a parent is present')

        self.document_root = self if root is None else root
        """Root :class:`jschon.json.JSON` object in the document."""


class OasJson(JSON):
    """
    Representation of an OAS-complaint API document.

    Based on and derived from :class:`jschon.json.JSON`

    :param uri: The identifier of this document, used for resolving references
    :param url: The locator of this document, from which it was loaded
    :param parent: The parent :class:`jschon.json.JSON` instance, if any
    :param key: The keyword under which this object appears in the parent
    :param itemclass: The class to use to instantiate child objects
    """

    def __init__(
        self,
        value,
        *,
        uri=None,
        url=None,
        parent=None,
        key=None,
        itemclass=None,
        catalog='oascomply',
        cacheid='default',
        **itemkwargs,
    ):
        logger.info(
            f'OasJson({{...}}, uri={str(uri)!r}, url={str(url)!r}, '
            f'parent={None if parent is None else id(parent)}, '
            f'key={key}, itemclass={itemclass}, catalog={catalog}, '
            f'cacheid={cacheid}, ...)',
        )

        self.document_root: Type[JSON]
        """Root :class:`jschon.json.JSON` object in the document."""

        self.oasversion: str
        """The major and minor (X.Y) part of the "openapi" version string"""

        if itemclass is None:
            itemclass = OasJson

        # We may be in the middle of constructing the root instance,
        # which results in not being able to cast it too boolean.
        # Therefore, compare it to None instead.
        # TODO: Figure out how to make this less fragile.
        if (root := itemkwargs.get('root')) is not None:
            self.document_root = root
            self.oasversion = root.oasversion
        else:
            self.document_root = self
            itemkwargs['root'] = self

            if 'oasversion' not in itemkwargs:
                if 'openapi' not in value:
                    raise ValueError(
                        f"{type(self)} requires the 'openapi' field "
                        "or an 'oasversion' constructor parameter",
                    )

                # Chop off patch version number
                itemkwargs['oasversion'] = value['openapi'][:3]
            self.oasversion = itemkwargs['oasversion']

        cacheid = self.oasversion

        if 'oas_metaschema_uri' not in itemkwargs:
            if itemkwargs['oasversion'] == '3.1':
                itemkwargs['oas_metaschema_uri'] = URI(value.get(
                    'jsonSchemaDialect',
                    "https://spec.openapis.org/oas/3.1/dialect/base",
                ))
            elif itemkwargs['oasversion'] == '3.0':
                itemkwargs['oas_metaschema_uri'] = URI(
                    "https://spec.openapis.org/oas/v3.0/dialect/base",
                )
            else:
                raise ValueError(
                    f"Unsupported OAS version {value['openapi']}",
                )
        self._oas_metaschema_uri = itemkwargs['oas_metaschema_uri']
        self._oasversion = itemkwargs['oasversion']
        if uri is None:
            # TODO: JsonPtr vs str
            self.uri = parent.uri.copy_with(
                fragment=rid.JsonPtr.parse_uri_fragment(
                    str(parent.uri.fragment),
                ) / key,
            )
        elif isinstance(uri, rid.UriWithJsonPtr):
            self.uri = uri
        else:
            self.uri = rid.UriWithJsonPtr(str(uri))

        if url is None:
            # TODO: JsonPtr vs str
            self.url = parent.url.copy_with(
                fragment=rid.JsonPtr.parse_uri_fragment(
                    str(parent.url.fragment),
                ) / key,
            )
        elif isinstance(url, rid.UriWithJsonPtr):
            self.url = url
        else:
            self.url = rid.UriWithJsonPtr(str(url))

        if not isinstance(catalog, Catalog):
            catalog = Catalog.get_catalog(catalog)

        # Track position with JSON Pointer fragments, so ensure we have one
        # TODO: Sometimes we don't want an empty fragment on the root document.
        if not self.uri.fragment:
            if self.uri.fragment is None:
                logger.debug(f"Adding '{self.uri}' to cache '{cacheid}'")
                catalog.add_schema(URI(str(self.uri)), self, cacheid=cacheid)
                self.uri = self.uri.copy_with(fragment='')
            else:
                logger.debug(
                    f"Adding '{self.uri.to_absolute()}' to cache '{cacheid}'",
                )
                catalog.add_schema(
                    URI(str(self.uri.to_absolute())),
                    self,
                    cacheid=cacheid,
                )
        if not self.url.fragment:
            self.url = self.url.copy_with(fragment='')

        self._schemakwargs = itemkwargs.copy()
        del self._schemakwargs['oasversion']
        del self._schemakwargs['oas_metaschema_uri']
        self._schemakwargs['catalog'] = catalog
        self._schemakwargs['cacheid'] = cacheid
        self._value = value

        super().__init__(
            value,
            parent=parent,
            key=key,
            itemclass=itemclass,
            **itemkwargs,
        )

    def convert_to_schema(self, key):
        if not isinstance(self.data[key], OasJsonSchema):
            # TODO: Figure out jschon.URI vs rid.Uri*
            # TODO: .value vs .data
            self.data[key] = OasJsonSchema(
                self.data[key].value,
                parent=self,
                key=key,
                uri=URI(str(
                    self.uri.copy_with(fragment=self.uri.fragment / key),
                )),
                metaschema_uri=URI(str(self._oas_metaschema_uri)),
                **self._schemakwargs,
            )
            self.data[key]._resolve_references()
        return self.data[key]
