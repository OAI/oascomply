from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal, Optional, Sequence, Union

import jschon
import jschon.exc


__all__ = [
    'URI',
    'URIError',
    'ThingToURI',
    'PathToURI',
    'URLToURI',
]


logger = logging.getLogger(__name__)


URI: TypeAlias = jschon.URI
"""URI alias for modules that otherwise have no need for jschon."""


URIError: TypeAlias = jschon.exc.URIError
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
