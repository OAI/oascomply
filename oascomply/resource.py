import logging
from collections import defaultdict
from pathlib import Path
from typing import (
    Any, ClassVar, Dict, Mapping, Optional, Sequence, Tuple, Type, Union,
)

import jschon
import jschon.exc
from jschon.jsonformat import JSONFormat
from jschon.catalog import Source
from jschon.vocabulary import Metaschema

import oascomply
from oascomply.oassource import (
    OASSource, DirectMapSource, FileMultiSuffixSource, HttpMultiSuffixSource,
)
from oascomply.oas3dialect import OAS30_SCHEMA, OAS31_SCHEMA


__all__ = [
    'OASJSONFormat',
    'OASResourceManager',
    'URI',
    'URIError',
    'ThingToURI',
    'PathToURI',
    'URLToURI',
]


logger = logging.getLogger(__name__)


URI = jschon.URI
"""URI alias for modules that otherwise have no need for jschon."""


URIError = jschon.exc.URIError
"""URI error alias for modules that otherwise have no need for jschon."""


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


class OASJSONFormat(JSONFormat):
    _default_metadocument_cls = Metaschema

    def __init__(self, *args, catalog='oascomply', **kwargs):
        self.oasversion = '3.0'
        self.sourcemap = None
        self.url = None
        super().__init__(*args, catalog='oascomply', **kwargs)


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
                        a_str = str(other_thing.uri) + a_str[len(other_str):]
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
        metadocument_uri,
        cls,
    ):
        base_uri = uri.copy(fragment=None)
        r = self._catalog.get_resource(
            uri,
            cacheid=oasversion,
            metadocument_uri=metadocument_uri,
            cls=cls,
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
        oasversion: str,
    ) -> Optional[OASJSONFormat]:
        uri = None
        if initial:
            uri = URI(initial) if isinstance(initial, str) else initial
        elif self._adjusted_files:
            uri = self._adjusted_files[0].uri
        elif self._adjusted_urls:
            uri = self._adjusted_urls[0].uri

        return None if uri is None else self.get_oas(uri, oasversion)

    def get_oas(
        self,
        uri: jschon.URI,
        oasversion: str,
        *,
        resourceclass: Type[jschon.JSON] = OASJSONFormat,
        oas_schema_uri: Optional[jschon.URI] = None,
    ):
        if oas_schema_uri is None:
            oas_schema_uri = {
                '3.0': OAS30_SCHEMA,
                '3.1': OAS31_SCHEMA,
            }[oasversion]

        oas_doc = self._get_with_url_and_sourcemap(
            uri,
            oasversion=oasversion,
            metadocument_uri=oas_schema_uri,
            cls=resourceclass,
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
