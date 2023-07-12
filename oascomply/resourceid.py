from __future__ import annotations

from functools import cached_property
import logging
from typing import overload, Iterable, Union
import urllib

import rfc3987
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
    def __init__(self, identifier):
        # cast to str to support ResourceIdentifier identifier values
        try:
            self._parsed = rfc3987.parse(str(identifier), rule=self._rule)
        except ValueError as e:
            raise self._uri_exc(str(e)) from e

        # keep file:/ vs file:/// renderings consistent
        # TODO: Using file:/, but file:/// is more familiar?
        #       jschon.URI seems to like file:/ ?
        if (
            self.scheme == 'file' and
            self.authority == ''
        ):
            self._parsed['authority'] = None
            self._parsed = rfc3987.parse(rfc3987.compose(**self._parsed))

    def __eq__(self, other):
        # TODO: This allows equality with plain strings and
        #       with othe URI-ish classes supporting str().
        #       Convenient, but possibly not a good idea?
        #
        #       We definitely *do* want equality within the
        #       ResourceIdentifier hierarchy, but that could
        #       be supported with an isinstance() check.
        return str(self) == str(other)

    def __str__(self):
        return self._parsed[self._rule]

    def __repr__(self):
        return f"{type(self).__name__}({self._parsed})"

    def __hash__(self):
        # This is for compatibility with jschon.URI
        # TODO: Ensure that we don't need strict compatibility as it is fragile.
        return hash(tuple(
            self.scheme,
            self.authority,
            self.path,
            self.query,
            self.fragment,
        ))

    @cached_property
    def scheme(self):
        return self._parsed['scheme']

    @cached_property
    def authority(self):
        return self._parsed['authority']

    @cached_property
    def path(self):
        return self._parsed['path']

    @cached_property
    def query(self):
        return self._parsed['query']

    @cached_property
    def fragment(self):
        return self._parsed['fragment']

    def is_absolute(self):
        return self.scheme is not None and self.fragment is None

    def has_absolute_base(self):
        return self.scheme is not None

    def to_absolute(self):
        if not self.scheme:
            abstype = self._rule[:4]
            raise self._uri_exc(
                'Cannot convert relative {abstype}-reference to absolute; '
                'call resolve() with a base {bastype} instead',
            )
        return self if self.fragment is None else self.copy(fragment=None)

    def resolve(self, base, return_parts=False):
        result = rfc3987.resolve(
            str(base),
            str(self),
            return_parts=return_parts
        )
        return result if return_parts else type(self)(result)

    def copy(
        self,
        cls=None,
        *,
        scheme=True,
        authority=True,
        path=True,
        query=True,
        fragment=True,
    ):
        # TODO: revisit jschon.URI compatibility hack
        if scheme is False:
            scheme = None
        if authority is False:
            authority = None
        if path in (False, None):
            raise ValueError('Cannot delete path!')
        if query is False:
            query = None
        if fragment is False:
            fragment = None

        if cls is None:
            cls = type(self)
        return cls(
            rfc3987.compose(
                scheme=self._parsed['scheme'] if scheme is True else scheme,
                authority=self._parsed['authority'] if authority is True else authority,
                path=self._parsed['path'] if path is True else path,
                query=self._parsed['query'] if query is True else query,
                fragment=self._parsed['fragment'] if fragment is True else fragment,
            ),
        )

    def validate(
        self,
        **kwargs,
        # require_scheme: bool = False,
        # require_normalized: bool = False,
        # allow_fragment: bool = True,
        # allow_non_empty_fragment: bool = True,
    ) -> None:
        # This is for jschon.uri.URI compatibility and not wanting
        # to re-implement it in rfc3987 package terms.  It is somewhat
        # redundant given the class hierarchy here, but it works for now.
        # TODO: better.
        if not hasattr(self, '_uriref'):
            import rfc3986
            self._uriref = rfc3986.uri_reference(str(self))
        super().validate(**kwargs)


class IriReference(ResourceIdentifier):
    """RFC 3987 IRI-reference production"""
    _rule = 'IRI_reference'


class Iri(IriReference):
    """RFC 3987 IRI production"""
    _rule = 'IRI'


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


# TODO: Would it be better to have this independent of IriReference
#       due to the different type of the fragment property?
#       Should the JSON Pointer object be exposed separately?
class IriReferenceWithJsonPtr(IriReference):
    def __init__(self, identifier):
        super().__init__(identifier)

    @cached_property
    def fragment_ptr(self):
        return (
            None if self._parsed['fragment'] is None
            else JsonPtr.parse_uri_fragment(self._parsed['fragment'])
        )


class IriWithJsonPtr(IriReferenceWithJsonPtr, Iri):
    _rule = 'IRI'


class UriReferenceWithJsonPtr(IriReferenceWithJsonPtr, UriReference):
    _rule = 'URI_reference'


class UriWithJsonPtr(IriWithJsonPtr, UriReferenceWithJsonPtr, Uri):
    _rule = 'URI'
