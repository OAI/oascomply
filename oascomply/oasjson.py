from __future__ import annotations

import re
import logging
import pathlib
from typing import (
    Hashable, Literal, Mapping, Optional, Sequence, Tuple, Type, TYPE_CHECKING, Union,
)
import json

import jschon
import jschon.utils
from jschon.jsonformat import JSONFormat
from jschon.vocabulary import Metaschema

from oascomply import resourceid as rid
from oascomply.exceptions import OASComplyError
from oascomply.oas30dialect import OAS30_DIALECT_METASCHEMA

if TYPE_CHECKING:
    from oascomply.oascatalog import OASCatalog

__all__ = [
    'OASJSON',
    'OASJSONSchema',
    'OASDocumentError',
    'OASUnsupportedVersionError',
    'OASVersionConflictError',
    'OASVersionMissingError',
]

logger = logging.getLogger(__name__)


class OASDocumentError(OASComplyError):
    pass

class OASVersionMissingError(OASDocumentError):
    pass

class OASUnsupportedVersionError(OASDocumentError):
    pass

class OASVersionConflictError(OASDocumentError):
    pass

class OASSchemaValidationError(OASComplyError):
    def __init__(self, error_detail):
        super().__init__('JSON Schema validation of OAS document failed!')

    @property
    def error_detail(self):
        return self.args[1]


class OASJSONMixin:
    """Interface for JSON classes implementing OAS documents"""

    SUPPORTED_OAS_VERSIONS = {
        '3.0':  {
            'schema': {
                'uri': "https://spec.openapis.org/compliance/schemas/oas/3.0/2023-06",
                'path': (
                    pathlib.Path(__file__).parent
                    / '..'
                    / 'schemas'
                    / 'oas'
                    / 'v3.0'
                    / 'schema.json'
                ).resolve(),
            },
            'dialect': {
                # We don't need a path as loading this dialect is managed by
                # the oascomply.oas30dialect module.
                'uri': OAS30_DIALECT_METASCHEMA,
                'vocab-meta': {},
            },
        },
        '3.1': {
            'schema': {
                'uri': "https://spec.openapis.org/oas/3.1/schema/2022-10-07",
                'path': (
                    pathlib.Path(__file__).parent
                    / '..'
                    / 'submodules'
                    / 'OpenAPI-Specification'
                    / 'schemas'
                    / 'v3.1'
                    / 'schema.json'
                ).resolve(),
            },
        },
    }

    _oasversion: Optional[str] = None

    @property
    def oasversion(self) -> str:
        """The major and minor (X.Y) part of the "openapi" version string"""
        if self._oasversion is None:
            if self is self.document_root:
                if 'openapi' not in self.data:
                    raise OASVersionMissingError(
                        f"{type(self)} requires the 'openapi' field "
                        "or an 'oasversion' constructor parameter",
                    )

                # Chop off patch version number
                # Assign through property for version check.
                self.oasversion = '.'.join(
                    self['openapi'].split('.')[:2],
                )
        return self._oasversion

    @oasversion.setter
    def oasversion(self, oasversion: str) -> None:
        self._set_oasversion(oasversion)

    def _set_oasversion(self, oasversion: str) -> None:
        if oasversion not in self.SUPPORTED_OAS_VERSIONS:
            raise OASUnsupportedVersionError(oasversion)

        if self is self.document_root:
            if (
                'openapi' in self.data and
                not (actual := self['openapi']).startswith(oasversion)
            ):
                raise OASVersionConflictError(
                    document_version=actual,
                    attempted_version=oasversion,
                    uri=self.uri,
                    url=self.url,
                )

        elif oasversion != (actual := self.document_root.oasversion):
            raise OASVersionConflictError(
                document_version=actual,
                attempted_version=oasversion,
                uri=self.uri,
                url=self.url,
            )

        self._oasversion = oasversion

    @property
    def url(self) -> Optional[jschon.URI]:
        """The location from which this resource was retrieved."""
        return self._url

    @url.setter
    def url(self, url: Optional[jschon.URI]) -> None:
        if self is self.document_root:
            self._url = url
        else:
            raise ValueError('Cannot set URL on non-root')

    @property
    def sourcemap(self) -> Optional[dict]:
        """Line and column number sourcemap, if enabled."""
        return (
            self._sourcemap if self is self.document_root
            else self.document_root._sourcemap
        )

    @sourcemap.setter
    def sourcemap(self, sourcemap: Optional[dict]) -> None:
        if self is self.document_root:
            self._sourcemap = sourcemap
        else:
            raise ValueError('Cannot set sourcemap on non-root')


class OASJSON(JSONFormat, OASJSONMixin):
    """
    Representation of an OAS-complaint API document.

    Based on and derived from :class:`jschon.json.JSON`

    :param uri: The identifier of this document, used for resolving references
    :param url: The locator of this document, from which it was loaded
    :param parent: The parent :class:`jschon.json.JSON` instance, if any
    :param key: The keyword under which this object appears in the parent
    :param itemclass: The class to use to instantiate child objects
    :param catalog:
    :param cacheid:
    :param oasversion: *[in `itemkwargs`]* The
    """

    _SCHEMA_PATH_REGEX = re.compile(
        r'(/components/schemas/[^/]*)|'
        r'(/paths/[^/]*/parameters/\d+/schema)|'
        r'(/paths/[^/]*/parameters/\d+/content/[^/]*/schema)|'
        r'(/paths/[^/]*/requestBody/content/[^/]*/schema)|'
        r'(/paths/[^/]*/responses/((default)|([1-5][0-9X][0-9X]))/content/[^/]*/schema)',
    )

    _default_metadocument_cls: Optional[
        ClassVar[Type[EvaluableJSON]]
    ] = jschon.JSONSchema

    @classmethod
    def get_oas_metadocument_uri(cls, oasversion):
        return jschon.URI(
            cls.SUPPORTED_OAS_VERSIONS[oasversion]['schema']['uri'],
        )

    @classmethod
    def get_schema_object_metaschema_uri(cls, oasversion):
        return jschon.URI(
            cls.SUPPORTED_OAS_VERSIONS[oasversion]['dialect']['uri'],
        )

    def __init__(
        self,
        value,
        *,
        uri=None,
        url=None,
        parent=None,
        key=None,
        oasversion: Optional[Literal['3.0', '3.1']] = None,
        sourcemap=None,
        itemclass: Type[jschon.JSON] = None,
        catalog: Union[str, OASCatlog] ='oascomply',
        **itemkwargs,
    ):
        if itemclass is None:
            itemclass = type(self)

        # Also set in superclass constructor, but needed prior to that.
        self.parent = parent

        if oasversion is not None:
            self._set_oasversion(oasversion)
        else:
            has_oasjson_parent = \
                parent is not None and isinstance(parent, OASJSON)
            if has_oasjson_parent:
                self._set_oasversion(parent.oasversion)
            elif 'openapi' in value:
                v = value['openapi']
                self._set_oasversion(v[:v.rindex('.')])
            else:
                raise OASVersionMissingError(
                    "OASJSON requires the oasversion parameter for document "
                    "roots if no 'openapi' field is present.",
                )
        
        from oascomply.oascatalog import OASCatalog
        if isinstance(catalog, str):
            catalog = OASCatalog.get_catalog(catalog)
        elif not isinstance(catalog, OASCatalog):
            raise TypeError(f"Expected OASCatlog, got {type(catalog).__name__}")

        # Use the X.Y oasversion as the cacheid
        # TODO: Is cacheid still needed in the __init__ arg list?  Maybe to
        #       keep it out of itemkwargs as we bounce through jschon code?
        cacheid = oasversion or '3.0' # self.oasversion

        super().__init__(
            value,
            parent=parent,
            key=key,
            uri=uri,
            catalog=catalog,
            # cacheid=cacheid,
            itemclass=itemclass,
            metadocument_uri=self.get_oas_metadocument_uri(oasversion or '3.0'),
            **itemkwargs,
        )

        if oasversion is not None:
            self.oasversion = oasversion

        if self.parent is None:
            self.sourcemap = sourcemap
            self.url = url

    def _get_itemclass(self, ptr):
        if self._SCHEMA_PATH_REGEX.fullmatch(str(ptr)):
            return OASJSONSchema
        return type(self)

    def instantiate_mapping(self, value):
        mapping = {}
        for k, v in value.items():
            itemclass = self._get_itemclass(
                self.path / k,
            )
            mapping[k] = itemclass(
                v,
                parent=self,
                key=k,
                catalog=self.catalog,
                **self.itemkwargs,
            )
        return mapping

#      def resolve_references(self) -> None:
#          if self.references_resolved == True:
#              return
#          result = self.validate()
#          if not result.valid:
#              raise OASSchemaValidationError(
#                  result.output('detailed'),
#              )
# 
#          # TODO: Filter annotations - standard and extension
#          self._annotations = [
#              Annotation(
#                  unit,
#                  instance_base=self.uri.copy(fragment=None),
#              ) for unit in result.output('basic')['annotations']
#          ]
# 
#     def get_annotations(
#         self,
#         name: Optional[str] = None,
#         value: Optional[str] = None,
#         instance_location: Optional[jschon.JSONPointer] = None,
#         schema_location: Optional[jschon.URI] = None,
#         evaluation_path: Optional[jschon.JSONPointer] = None,
#         single: bool = False,
#         required: bool = False,
#     ) -> Optional[Union[Annotation, Sequence[Annotation]]]:
#         """
#         """
#         if self._annotations is None:
#             self.validate()
# 
#         annotations = [
#             a for a in self._annotations
#             if (
#                 (name is None or name == a.keyword) and
#                 (value is None or value == a.value) and
#                 (
#                     instance_location is None or
#                     instance_location == a.location.instance_ptr
#                 ) and (
#                     schema_location is None or
#                     schema_location == a.location.schema_uri
#                 ) and (
#                     evaluation_path is None or
#                     evaluation_path == a.location.evaluation_path_ptr
#                 )
#             )
#         ]
#         if required and not annotations:
#             raise ValueError("No annotations matched!")
#         if single:
#             if len(annotations) > 1:
#                 raise ValueError("Multiple annotations matched!")
#             return annotations[0] if annotations else None
#         return annotations


class OASJSONSchema(jschon.JSONSchema, OASJSONMixin):
    def __init__(
        self,
        value,
        *args: Any,
        oasversion: Optional[Literal['3.0', '3.1']] = None,
        metadocument_uri: Optiona[URI] = None,
        **kwargs: Any,
    ):
        self.parent = kwargs.get('parent')

        if oasversion is not None:
            self._set_oasversion(oasversion)

        if metadocument_uri is None:
            if self.oasversion == '3.0':
                self.metadocument_uri = jschon.URI(OAS30_DIALECT_METASCHEMA)
            elif self.oasversion == '3.1':
                self.metadocument_uri = jschon.URI(self.document_root.data.get(
                    'jsonSchemaDialect',
                    "https://spec.openapis.org/oas/3.1/dialect/base",
                ))
            else:
                raise ValueError(
                    f"Unsupported OAS version {self.oasversion}",
                )
        else:
            self.metadocument_uri = metadocument_uri

        assert self.metadocument_uri is not None
        assert self.metaschema_uri == self.metadocument_uri

        super().__init__(
            value,
            *args,
            metaschema_uri=self.metadocument_uri,
            **kwargs,
        )

    def pre_recursion_init(self, *args, **kwargs):
        super().pre_recursion_init(*args, **kwargs)
        assert self.metadocument_uri is not None
        assert self.metaschema_uri == self.metadocument_uri
        md = self.metadocument
        ms = self.metaschema
            
    @property
    def oasversion(self) -> str:
        if self.document_root is self:
            return self._oasversion
        return self.document_root.oasversion

    def is_format_root(self) -> bool:
        return (
            self.type == 'object' and
            '$id' in self.data and '$schema' in self.data
        ) or self.format_parent is None

    def is_resource_root(self) -> bool:
        return (
            self.oasversion == '3.1' and self.type == 'object' and
            '$id' in self.data
        ) or self.parent is None
