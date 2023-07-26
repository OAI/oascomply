from __future__ import annotations

from functools import cached_property
import logging
from typing import overload, Iterable, Union
import urllib

import jschon

__all__ = [
    'JsonPtr',
    'RelJsonPtr',
    'Iri',
    'IriReference',
    'Uri',
    'UriReference',
    'IriWithJsonPtr',
    'IriReferenceWithJsonPtr',
    'UriWithJsonPtr',
    'UriReferenceWithJsonPtr',
    'URIString',
    'URIReferenceString',
    'AnyURI',
    'AnyURIReference',
    'AnyURIManager',
]

logger = logging.getLogger(__name__)


URIString = str
URIReferenceString = str
AnyURI = Union[URIString, jschon.URI, 'Iri']
AnyURIRef = Union[URIString, jschon.URI, 'IriReference']


class ResourceIdentifier(jschon.URI):
    """Abstract base class for RFC 3986/7 resource identifiers"""
    def to_absolute(self):
        if self.scheme is not None:
            return self.copy(fragment=None)
        else:
            raise ValueError(
                'Cannot convert relative {abstype}-reference to absolute; '
                'call resolve() with a base instead',
            )


class IriReference(ResourceIdentifier):
    """RFC 3987 IRI-reference production"""
    _rule = 'IRI_reference'

class Iri(IriReference):
    """RFC 3987 IRI production"""
    _rule = 'IRI'

    def __init__(self, identifier):
        super().__init__(identifier)
        self.validate(require_scheme=True)


class UriReference(IriReference):
    """RFC 3986 URI-reference production"""
    _rule = 'URI_reference'


class Uri(Iri, UriReference):
    """RFC 3986 URI production"""
    _rule = 'URI'


class RelJsonPtr(jschon.RelativeJSONPointer):
    pass


class JsonPtr(jschon.JSONPointer):
    @overload
    def __truediv__(self, suffix: str) -> JsonPtr:
        ...

    @overload
    def __truediv__(self, suffix: Iterable[str]) -> JsonPtr:
        ...

    @overload
    def __truediv__(self, suffix: RelJsonPtr) -> JsonPtr:
        ...

    def __truediv__(self, suffix):
        """Return `self / suffix`."""
        if isinstance(suffix, RelJsonPtr):
            if suffix.index:
                raise ValueError(
                    f"{self} / {suffix}: cannot use / with trailing '#'",
                )
            p = self
            l = len(self)
            if suffix.up:
                if suffix.up > l:
                    raise ValueError(
                        f"{self} / {suffix}: parent {suffix.up} too high",
                    )
                p = self[:-suffix.up]
            if suffix.over:
                if l == 0:
                    raise ValueError(
                        f"{self} / {suffix}: can't adjust index without parent",
                    )
                try:
                    idx = int(p[-1])
                    p = p[:-1] / str(idx + suffix.over)
                except ValueError as e:
                    raise ValueError(
                        f"{self} / {suffix}: can't adjust non-integer index",
                    ) from e
            if suffix.path:
                p = p / suffix.path
            return p

        return JsonPtr(str(super().__truediv__(suffix)))


class IriReferenceWithJsonPtr(IriReference):
    _rule = 'IRI_reference'

    @cached_property
    def fragment_ptr(self):
        return (
            None if self.fragment is None
            else JsonPtr.parse_uri_fragment(self.fragment)
        )


class IriWithJsonPtr(IriReferenceWithJsonPtr, Iri):
    _rule = 'IRI'


class UriReferenceWithJsonPtr(IriReferenceWithJsonPtr, UriReference):
    _rule = 'URI_reference'


class UriWithJsonPtr(IriWithJsonPtr, UriReferenceWithJsonPtr, Uri):
    _rule = 'URI'
