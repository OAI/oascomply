from __future__ import annotations

import re
import logging
import pathlib
from os import PathLike
from dataclasses import dataclass
from typing import Hashable, Mapping, Optional, Sequence, Tuple, Type, Union
import json

import jschon
import jschon.utils
from jschon.exc import CatalogError
from jschon.catalog import Catalog, Source, LocalSource, RemoteSource

import yaml
import rfc3339
import json_source_map as jmap
import yaml_source_map as ymap
from yaml_source_map.errors import InvalidYamlError

from oascomply.ptrtemplates import (
    JSON_POINTER_TEMPLATE, RELATIVE_JSON_POINTER_TEMPLATE,
    RelJsonPtrTemplate,
)
from oascomply.oas3dialect import OAS30_DIALECT_METASCHEMA

__all__ = [
    'DirectMapSource',
    'FileMultiSuffixSource',
    'HttpMultiSuffixSource',
]

logger = logging.getLogger(__name__)


PathString = str
Suffix = str
Content = str


@dataclass(frozen=True)
class LoadedContent:
    content: str
    url: URIString
    parse_type: str


@dataclass(frozen=True)
class ParsedContent:
    value: jschon.JSONCompatible
    url: URIString
    sourcemap: Union[dict, None]


class ResourceLoader:
    @classmethod
    def load(cls, location: str) -> LoadedContent:
        raise NotImplementedError


class FileLoader(ResourceLoader):
    @classmethod
    def load(cls, full_path: PathString) -> LoadedContent:
        """Load a file, returning the contents and the retrieval URL"""
        path = pathlib.Path(full_path)
        content = path.read_text(encoding='utf-8')
        parse_type = None
        if path.suffix in ContentParser.SUPPORTED_SUFFIXES:
            parse_type = path.suffix

        return LoadedContent(
            content=content,
            url=path.as_uri(),
            parse_type=parse_type,
        )


class HttpLoader(ResourceLoader):
    @classmethod
    def load(cls, url: URIString) -> LoadedContent:
        raise NotImplementedError


class ContentParser:
    SUPPORTED_SUFFIXES = ('.json', '.yaml', '.yml')
    """Suffixes for which we have parsers, when a media type is unavailable"""

    def __init__(self, loaders: Tuple[ResourceLoader]):
        self._loaders = loaders

    def get_parser(self, content_info):
        """Map of file suffixes and media types to parsing functions."""
        return {
            None: self._unknown_parse,
            # TODO: Think deeper about media types and ranges.
            #       Currently, nothing fetches media types yet anyway.
            # 'application/json': self._json_parse,
            # 'application/openapi+json': self._json_parse,
            # 'application/schema+json': self._json_parse,
            # 'application/*+json': self._json_parse,
            # 'application/yaml': self._yaml_parse,
            # 'application/openapi+yaml': self._yaml_parse,
            # 'application/schema+yaml': self._yaml_parse,
            # 'application/*+yaml': self._yaml_parse,
            '': self._unknown_parse,
            '.json': self._json_parse,
            '.yaml': self._yaml_parse,
            '.yml': self._yaml_parse,
        }[content_info]

    def parse(
        self,
        full_path: str,
        content_info: str,
        create_source_map: bool = False,
    ) -> ParsedContent:
        return self.get_parser(content_info)(full_path, create_source_map)

    def _json_parse(
        self,
        full_path: str,
        create_source_map: bool = False,
    ) -> ParsedContent:
        """Load a JSON document, optionally with source line and column map."""
        sourcemap = None
        loaded = self.load(full_path)
        try:
            data = jschon.utils.json_loads(loaded.content)
            if create_source_map:
                logger.info(
                    f'Creating JSON sourcemap for {path}, '
                    '(can disable with -n if slow)',
                )
                sourcemap = jmap.calculate(content)
            return ParsedContent(
                value=data,
                url=pathlib.Path(full_path).as_uri(),
                sourcemap=sourcemap,
            )
        except json.JSONDecodeError as e:
            raise CatalogError(str(e)) from e

    def _yaml_parse(
        self,
        full_path: str,
        create_source_map: bool = False,
    ) -> ParsedContent:
        """Load a YAML document, optionally with source line and column map."""
        sourcemap = None
        logger.info(f"Loading {full_path} as YAML...")
        loaded = self.load(full_path)
        try:
            data = yaml.safe_load(loaded.content)
            if create_source_map:
                try:
                    logger.info(
                        f'Creating YAML sourcemap for {path}, '
                        '(can disable with -n if slow)',
                    )
                    sourcemap = ymap.calculate(content)
                except InvalidYamlError:
                    # The YAML source mapper gets confused sometimes,
                    # even with YAML that parses correctly,
                    # so just log a warning and work without the map.
                    logger.warn(
                        f"Unable to calculate source map for {path}",
                    )
            return ParsedContent(value=data, url=loaded.url, sourcemap=sourcemap)
        except InvalidYamlError:
            raise CatalogError(str(e)) from e

    def _unknown_parse(
        self,
        full_path: str,
        create_source_map: bool = False,
    ) -> ParsedContent:
        """
        Load a file of unknown type by trying first JSON then YAML.
        """
        try:
            return self._json_parse(full_path, create_source_map)
        except CatalogError as e1:
            logger.warning(
                f"Failed to parse file {full_path} of unknown type "
                f"as JSON:\n\t{e1}",
            )
            try:
                return self._yaml_parse(full_path, create_source_map)
            except CatalogError as e2:
                logger.warning(
                    f"Failed to parse file {full_path} of unknown type "
                    f"as YAML:\n\t{e2}",
                )
                raise CatalogError(
                    "Could not determine content type of '{full_path}'",
                )

    def load(self, location: str) -> LoadedContent:
        errors = []
        for loader in self._loaders:
            try:
                return loader.load(location)
            except CatalogError as e:
                errors.append(e)

        if len(errors) == 1:
            raise errors[0]

        # TODO: This could be better
        raise CatalogError(
            f'Could not load from {location!r}, errors:\n\t' +
            '\n\t'.join([str(err) for err in errors]),
        )


class OASSource(Source):
    """
    Source that tracks loading information and uses modular parsers/loaders.

    The :class:`jschon.catalog.Catalog` interface does not provide
    a way to pass extra information back with a loaded document,
    or to the :clas:`jschon.jsonschema.JSONSchema` constructor when
    loading schemas.

    This class is for use with :class:`OASCatalog`, which uses
    it's properties to register data structures for storing such
    information under each resource's lookup URI.  It is assumed
    that the data structures are shared across all :class:`OASSource`
    instances within an :class:`OASCatalog`.

    Additionally, it defers the actual loading and parsing of resources
    to a modular system that handles different I/O channels and data formats.
    """

    # TODO: Maybe the maps are class attributes?

    def __init__(
        self,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._parser = ContentParser(self.get_loaders())
        self._uri_url_map = {}
        self._uri_sourcemap_map = {}

        # TODO: Not always accurate, but a good initial state?
        self.set_uri_prefix(None)

    @classmethod
    def get_loaders(cls) -> Tuple[ResourceLoader]:
        raise NotImplementedError

    def set_uri_url_map(self, mapping: Mapping[jschon.URI, jschon.URI]):
        self._uri_url_map = mapping

    def set_uri_sourcemap_map(self, mapping: Optional[dict]) -> None:
        self._uri_sourcemap_map = mapping

    def map_url(
        self,
        relative_path: str,
        url: URIString,
    ) -> None:
        uri = jschon.URI(str(self._uri_prefix) + relative_path)
        logger.debug(f"Resolved URI <{uri}> via URL <{url}>")
        self._uri_url_map[uri] = url

    def map_sourcemap(
        self,
        relative_path: str,
        sourcemap: Optional[dict],
    ) -> None:
        self._uri_sourcemap_map[
            jschon.URI(str(self._uri_prefix) + relative_path)
        ] = sourcemap

    @property
    def uri_prefix(self) -> URIString:
        """The base URI / URI prefix under which this source is registered."""
        return self._base_uri

    def set_uri_prefix(self, base_uri: URIString) -> None:
        self._uri_prefix = '' if base_uri is None else base_uri

    def resolve_resource(
        self,
        relative_path: str,
    ) -> ParsedContent:
        raise NotImplementedError

    def __call__(self, relative_path: str):
        content = self.resolve_resource(relative_path)
        self.map_url(relative_path, jschon.URI(content.url))
        self.map_sourcemap(relative_path, content.sourcemap)
        return content.value


class MultiSuffixSource(OASSource):
    """
    Source that appends each of a list of suffixes before attempting to load.

    Subclasses are expected to map an appropriate callable to each supported
    suffix, which can include an empty string for un-suffixed locations.
    Non-empty suffixes MUST include any leading ``.`` character that
    would not be present in the requested URI.

    The content is returned from the first suffix that can be loaded
    successfully.

    :param suffixes: The list of suffixes to search in order.
    """
    def __init__(
        self,
        prefix: str,
        *,
        suffixes: Sequence[Suffix] = ('', '.json', '.yaml'),
        **kwargs,
    ) -> None:

        self._prefix = self._validate_prefix(prefix)
        self._suffixes: Sequence[Suffix] = suffixes
        """The suffixes to search, in order."""

        super().__init__(**kwargs)

    @property
    def prefix(self) -> URIStringReference:
        return self._prefix

    def _validate_prefix(self, prefix: str) -> str:
        """
        Validates, normalizes, and returns the prefix.

        By default, returns the prefix as is. Subclasses should override
        as needed.
        """
        return prefix

    def resolve_resource(
        self,
        relative_path: str,
    ) -> ParsedContent:
        """
        Appends each suffix in turn, and attempts to load using the map.

        :returns: A tuple of the loaded data followed by the URL from
            which it was loaded.
        :raise jschon.exc.CatalogError: if no suffix could be loaded
            successfully.
        """
        no_suffix_path = self.prefix + relative_path

        logger.debug(
            f'Checking "{no_suffix_path}" with suffixes {self._suffixes}',
        )
        for suffix in self._suffixes:
            full_path = no_suffix_path + suffix
            try:
                return self._parser.parse(full_path, suffix)
            except FileNotFoundError:
                pass
            except KeyError as e:
                logger.warning(
                    f'Unsupported suffix {suffix!r} while loading '
                    f'from "{full_path}"',
                )

        raise CatalogError(
            f"Could not find '{no_suffix_path}', "
            f"checked extensions {self._suffixes}"
        )


class FileMultiSuffixSource(MultiSuffixSource, FileLoader):
    def _validate_prefix(self, prefix: str) -> str:
        resource_dir = pathlib.Path(prefix).resolve()
        if not resource_dir.is_dir():
            raise ValueError(f'{prefix!r} must be an existing directory!')

        # Trailing slash required because of blind use as a prefix by jschon
        return f'{resource_dir}/'

    @classmethod
    def get_loaders(self) -> Tuple[ResourceLoader]:
        return (FileLoader,)


class HttpMultiSuffixSource(MultiSuffixSource, HttpLoader):
    def _validate_prefix(self, prefix: str) -> str:
        parsed_prefix = jschon.URI(prefix)
        if not parsed_prefix.path.endswith('/'):
            raise ValueError(f'{prefix!r} must contain a path ending with "/"')

        return str(parsed_prefix)

    @classmethod
    def get_loaders(self) -> Tuple[ResourceLoader]:
        return (HttpLoader,)


class DirectMapSource(OASSource):
    """Source for loading URIs with known exact locations."""
    def __init__(
        self,
        location_map: Mapping[jschon.URI, Union[jshchon.URI, pathlib.Path]],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._map = location_map.copy()

    def update_map(self, mapping):
        """
        Update the map as only one no-prefix source can exist per catalog.
        """
        self._map.update(mapping)

    def resolve_resource(
        self,
        relative_path: str,
    ) -> ParsedContent:
        if (location := self._map.get(jschon.URI(relative_path))) is None:
            raise CatalogError(f'Requested unknown resource {relative_path!r}')

        try:
            suffix = location.suffix
        except AttributeError:
            loc_str = str(location)
            if '/' in loc_str and '.' in loc_str[loc_str.rindex('/') + 1:]:
                suffix = loc_str[loc_str.rindex('.'):]
            else:
                suffix = ''
        logger.debug(f"Requesting parse('{location}', '{suffix}')")
        return self._parser.parse(location, suffix)

    @classmethod
    def get_loaders(self) -> Tuple[ResourceLoader]:
        return (FileLoader, HttpLoader)
