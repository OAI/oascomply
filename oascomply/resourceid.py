from functools import cached_property
import logging
from typing import overload
import urllib

import rfc3987
import jschon

__all__ = [
    'JsonPtr', 'RelJsonPtr',
    'Iri', 'IriReference', 'Uri', 'UriReference',
    'IriWithJsonPtr', 'IriReferenceWithJsonPtr',
    'UriWithJsonPtr', 'UriReferenceWithJsonPtr',
]

logger = logging.getLogger(__name__)

class ResourceIdentifier:
    """Abstract base class for RFC 3986/7 resource identifiers"""
    def __init__(self, identifier):
        # cast to str to support ResourceIdentifier identifier values
        self._parsed = rfc3987.parse(str(identifier), rule=self._rule)

        # keep file:/ vs file:/// renderings consistent
        # TODO: This uses file:/// as more familiar, but would it
        #       be better to use file:/ as more correct per RFC 8089?
        #       Older code might not like file:/ so use file:/// for now.
        if (
            self.scheme == 'file' and
            self.authority is None
        ):
            self._parsed['authority'] = ''
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
        return hash(str(self))

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

    def to_absolute(self):
        if not self.scheme:
            abstype = self._rule[:4]
            raise ValueError(
                'Cannot convert relative {abstype}-reference to absolute; '
                'call resolve() with a base {bastype} instead',
            )
        return self if self.fragment is None else self.copy_with(fragment=None)

    def resolve(self, base, return_parts=False):
        result = rfc3987.resolve(
            str(base),
            str(self),
            return_parts=return_parts
        )
        return result if return_parts else type(self)(result)

    def copy_with(
        self,
        cls=None,
        *,
        scheme=True,
        authority=True,
        path=True,
        query=True,
        fragment=True,
    ):
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
    def __eq__(self, other):
        # TODO: See similar note on ResourceIdentifier.str
        #       Doing this allows x.fragment to be equal
        #       for normal vs WithJsonPtr classes.  Is that
        #       ideal?  Should it be handled another way?
        return str(self) == str(other)

    def __repr__(self):
        return f"RelJsonPtr({str(self)!r})"


class JsonPtr(jschon.JSONPointer):
    @classmethod
    def parse_uri_fragment(cls, value):
        return JsonPtr(urllib.parse.unquote(value))

    def __eq__(self, other):
        # TODO: See similar note on ResourceIdentifier.str
        #       Doing this allows x.fragment to be equal
        #       for normal vs WithJsonPtr classes.  Is that
        #       ideal?  Should it be handled another way?
        return str(self) == str(other)

    def __repr__(self):
        return f"JsonPtr({str(self)!r})"

    def __hash__(self):
        return super().__hash__()

    @overload
    def __truediv__(self, suffix: RelJsonPtr):
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

    def __getitem__(self, index):
        if isinstance(index, int):
            return self._keys[index]
        if isinstance(index, slice):
            return JsonPtr(str(super().__getitem__(index)))


# TODO: Would it be better to have this independent of IriReference
#       due to the different type of the fragment property?
#       Should the JSON Pointer object be exposed separately?
class IriReferenceWithJsonPtr(IriReference):
    def __init__(self, identifier):
        super().__init__(identifier)

    def __repr__(self):
        return f"{type(self).__name__}({self._parsed}, {self.fragment!r})"

    @cached_property
    def fragment(self):
        return (
            None if self._parsed['fragment'] is None
            else JsonPtr.parse_uri_fragment(self._parsed['fragment'])
        )

    def copy_with(
        self,
        cls=None,
        *,
        fragment=True,
        **kwargs,
    ):
        if isinstance(fragment, JsonPtr):
            fragment = fragment.uri_fragment()
        return super().copy_with(cls, fragment=fragment, **kwargs)


class IriWithJsonPtr(IriReferenceWithJsonPtr, Iri):
    _rule = 'IRI'


class UriReferenceWithJsonPtr(IriReferenceWithJsonPtr, UriReference):
    _rule = 'URI_reference'


class UriWithJsonPtr(IriWithJsonPtr, UriReferenceWithJsonPtr, Uri):
    _rule = 'URI'
