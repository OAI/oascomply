from __future__ import annotations

import re
import logging
import pathlib
from typing import Hashable, Mapping, Optional, Sequence, Tuple, Type, TYPE_CHECKING, Union
import json

import jschon
import jschon.utils
from jschon.jsonschema import JSONSchemaContainer

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
]

logger = logging.getLogger(__name__)


class OASDocumentError(OASComplyError):
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

    @property
    def oasversion(self) -> str:
        """The major and minor (X.Y) part of the "openapi" version string"""
        if self._oasversion is None:
            if self is self.document_root:
                if 'openapi' not in self.data:
                    raise ValueError(
                        f"{type(self)} requires the 'openapi' field "
                        "or an 'oasversion' constructor parameter",
                    )

                # Chop off patch version number
                # Assign through property for version check.
                self.oasversion = '.'.join(
                    self.data['openapi'].split('.')[:2],
                )
        return self._oasversion

    @oasversion.setter
    def oasversion(self, oasversion: str) -> None:
        if oasversion not in OASCatalog.SUPPORTED_OAS_VERSIONS:
            raise OASUnsupportedVersionError(
                oasversion, uri=self.uri, url=self.url,
            )

        if (
            'openapi' in self.data and
            not (actual := self.data['openapi']).startswith(oasversion)
        ):
            raise OASVersionConflictError(
                document_version=actual,
                attempted_version=oasversion,
                uri=self.uri,
                url=self.url,
            )

        if (
            self is not self.document_root and
            oasversion != (actual := self.document_root.oasversion)
        ):
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


class OASJSON(JSONSchemaContainer, OASJSONMixin):
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
            },
        },
    }

    @classmethod
    def get_oas_schema_uri(cls, oasversion):
        return cls._metaschema_cls._uri_cls(
            self.SUPPORTED_OAS_VERSIONS[oasversion]['schema']['uri'],
        )

    @classmethod
    def get_metaschema_uri(cls, oasversion):
        return cls._metaschema_cls._uri_cls(
            self.SUPPORTED_OAS_VERSIONS[oasversion]['dialect']['uri'],
        )

    _uri_cls: ClassVar[Type[rid.IriReference]] = rid.IriReference
    _catalog_cls: ClassVar[Type[OASCatalog]]

    @classmethod
    def _set_catalog_cls(cls, catalog_cls):
        from oascomply.oascatalog import OASCatalog
        cls._catalog_cls = OASCatalog

    def __init__(
        self,
        value,
        *,
        uri=None,
        url=None,
        parent=None,
        key=None,
        oasversion=None,
        sourcemap=None,
        itemclass=None,
        catalog='oascomply',
        **itemkwargs,
    ):
        logger.info(
            f'{id(self)} == OASJSON({{...}}, uri={str(uri)!r}, url={str(url)!r}, '
            f'parent={None if parent is None else id(parent)}, '
            f'key={key}, itemclass={itemclass}, catalog={catalog}, '
            f'cacheid={cacheid}, ...)',
        )

        if oasversion is not None:
            self.oasversion = oasversion
        if parent is None:
            self.sourcemap = sourcemap
            self.url = url

        if itemclass is None:
            itemclass = type(self)

        if not isinstance(catalog, self._catalog_cls):
            catalog = self._catalog_cls.get_catalog(catalog)

        # Use the X.Y oasversion as the cacheid
        # TODO: Is cacheid still needed in the __init__ arg list?  Maybe to
        #       keep it out of itemkwargs as we bounce through jschon code?
        cacheid = self.oasversion

        super().__init__(
            value,
            parent=parent,
            key=key,
            uri=uri,
            catalog=catalog,
            cacheid=self.oasversion,
            itemclass=itemclass,
            **itemkwargs,
        )

    def _get_itemclass(self, ptr):
        if self._SCHEMA_PATH_REGEX.fullmatch(str(ptr)):
            return OASJSONSchema
        return type(self)

    def instantiate_mapping(self, value):
        itemclass = self._get_itemclass(
            self.path / k,
        )
        return {
            k: itemclass(
                parent=self,
                key=k,
                **self.itemkwargs,
            ) for k, v in value.items()
        }

    def resolve_references(self) -> None:
        if self.references_resolved == True:
            return
        result = self.validate()
        if not result.valid:
            raise OASSchemaValidationError(
                result.output('detailed'),
            )

        # TODO: Filter annotations - standard and extension
        self._annotations = [
            Annotation(
                unit,
                instance_base=self.uri.copy(fragment=None),
            ) for unit in result.output('basic')['annotations']
        ]

    @property
    def metaschema_uri(self) -> Optional[jschon.URI]:
        """The OAS format schema for this document node.

        Only document nodes with an ``oastype`` annotation have
        metaschemas (see :class:`OASJSONSchema` for special handling
        for Schema Objects).
        """
        return self.get_oas_schema_uri(self.oasversion)

        if self._metaschema_uri is not None:
            return self._metaschema_uri
         
        # TODO: Idea of per-oastype-object metaschemas?
        # self._metaschema_uri = self.get_annotation(
        #     name='oastype',
        #     instance_location=self.path,
        #     single=True,
        # ).schema_uri

    @metaschema_uri.setter
    def metaschema_uri(self, metaschema_uri: Optional[URI]) -> None:
        # Used by the parent class, duplicated because @property
        self._metaschema_uri = metaschema_uri

    def get_annotations(
        self,
        name: Optional[str] = None,
        value: Optional[str] = None,
        instance_location: Optional[jschon.JSONPointer] = None,
        schema_location: Optional[jschon.URI] = None,
        evaluation_path: Optional[jschon.JSONPointer] = None,
        single: bool = False,
        required: bool = False,
    ) -> Optional[Union[Annotation, Sequence[Annotation]]]:
        """
        """
        if self._annotations is None:
            self.validate()

        annotations = [
            a for a in self._annotations
            if (
                (name is None or name == a.keyword) and
                (value is None or value == a.value) and
                (
                    instance_location is None or
                    instance_location == a.location.instance_ptr
                ) and (
                    schema_location is None or
                    schema_location == a.location.schema_uri
                ) and (
                    evaluation_path is None or
                    evaluation_path == a.location.evaluation_path_ptr
                )
            )
        ]
        if required and not annotations:
            raise ValueError("No annotations matched!")
        if single:
            if len(annotations) > 1:
                raise ValueError("Multiple annotations matched!")
            return annotations[0] if annotations else None
        return annotations


class OASJSONSchema(JSONSchemaContainer, OASJSONMixin):
    _catalog_cls: ClassVar[Type[OASCatalog]]

    @classmethod
    def _set_catalog_cls(cls):
        from oascomply.oascatalog import OASCatalog
        cls._catalog_cls = OASCatalog

    # TODO: __init__ really needs to do this?
    def __init__(self, *args, **kwargs):
        self._set_catalog_cls()
        super().__init__(*args, **kwargs)

    @property
    def oasversion(self) -> str:
        return self.document_root.oasversion

    @property
    def metaschema_uri(self) -> Optional[jschon.URI]:
        if (m := super().metaschema_uri) is not None:
            return m
        elif self.oasversion == '3.0':
            return self._uri_cls(OAS30_DIALECT_METASCHEMA)
        elif self.oasversion == '3.1':
            return self._uri_cls(self.document_root.data.get(
                'jsonSchemaDialect',
                "https://spec.openapis.org/oas/3.1/dialect/base",
            ))
        else:
            raise ValueError(
                f"Unsupported OAS version {self.oasversion}",
            )

    @metaschema_uri.setter
    def metaschema_uri(self, metaschema_uri: Optional[URI]) -> None:
        # Used by the parent class, duplicated because @property
        self._metaschema_uri = metaschema_uri
