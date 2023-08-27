import json
from functools import cached_property
from pathlib import Path
from uuid import uuid4
from typing import Any, Optional, Union
import logging

import jschon
import rdflib
from rdflib.namespace import RDF
import yaml

from oascomply.resource import OAS_SCHEMA_INFO

__all__ = [
    'initialize_oas_specification_schemas',
    'Annotation',
    'SchemaParser',
]

logger = logging.getLogger(__name__)


def initialize_oas_specification_schemas(catalog: jschon.Catalog):
    for oasversion, oasinfo in OAS_SCHEMA_INFO.items():
        # As a metaschema, the OAS schema behaves like the corresponding
        # dialect metaschema as that is what it should use by default when
        # it encounters a Schema Object.  Objects between the document root
        # and the Schema Objects are not JSONSchema subclasses and are
        # therefore treated like regular instance validation.
        catalog.create_metaschema(
            jschon.URI(oasinfo['schema']['uri']),
            *oasinfo['schema']['vocabs']
        )


class JsonSchemaParseError(ValueError):
    def __init__(self, error_detail):
        super().__init__('JSON Schema valiation failed!', error_detail)

    @property
    def error_detail(self):
        return self.args[1]


class Annotation:
    def __init__(self, unit, instance_base=None):
        self._location = Location.get(unit, instance_base)
        self._keyword = unit['keywordLocation'][
            unit['keywordLocation'].rindex('/') + 1:
        ]
        self._value = unit['annotation']

    def __repr__(self):
        return (
            f'Annotation({self._keyword}={self._value!r}, '
            f'{self._location!r})'
        )

    @property
    def location(self):
        return self._location

    @property
    def keyword(self):
        return self._keyword

    @property
    def value(self):
        return self._value


class Location:
    _cache = {}

    @classmethod
    def _get_instance_base_uri(cls, base=None):
        if base:
            if isinstance(base, jschon.URI):
                return base
            else:
                return jschon.URI(str(base))
        try:
            return cls._default_instance_base
        except AttributeError:
            # NOTE: This ony works if there is only one instance document.
            # TODO: Guard against messing it up?  Do we even need this?
            cls._dibu = jschon.URI(f'urn:uuid:{uuid4()}')
        return cls._default_instance_base

    @classmethod
    def get(cls, unit: dict, instance_base: Union[str, jschon.URI] = None):
        eval_ptr = jschon.JSONPointer(unit['keywordLocation'])[:-1]

        cache_key = (
            cls._get_instance_base_uri(instance_base),
            unit['instanceLocation'],
            eval_ptr,
        )
        try:
            return cls._cache[cache_key]
        except KeyError:
            loc = Location(
                unit,
                eval_ptr=eval_ptr,
                instance_base=instance_base,
            )
            cls._cache[cache_key] = loc
            return loc

    def __init__(
        self,
        unit,
        *,
        eval_ptr=None,
        instance_base=None
    ):
        self._unit = unit
        self._given_base = instance_base
        self._eval_ptr = (
            jschon.JSONPointer(unit['keywordLocation'])[:-1] if eval_ptr is None
            else eval_ptr
        )

    def __hash__(self):
        return hash((self._instance_uri, self._eval_ptr))

    def __repr__(self):
        return (
            f'{type(self).__name__}({self._unit!r}, '
            f'instance_base={self._given_base!r}, eval_ptr={self._eval_ptr!r})'
        )

    @cached_property
    def instance_resource_uri(self) -> jschon.URI:
        return jschon.URI(
            str(self._get_instance_base_uri(self._given_base)),
        )

    @cached_property
    def instance_uri(self) -> jschon.URI:
        return self.instance_resource_uri.copy(
           fragment=self.instance_ptr.uri_fragment(),
        )

    @cached_property
    def instance_ptr(self) -> jschon.JSONPointer:
        return jschon.JSONPointer(self._unit['instanceLocation'])

    @cached_property
    def evaluation_path_ptr(self) -> jschon.JSONPointer:
        return self._eval_ptr

    @cached_property
    def schema_resource_uri(self) -> jschon.URI:
        return self.schema_uri.to_absolute()

    @cached_property
    def schema_uri(self) -> jschon.URI:
        s_uri = jschon.URI(self._unit['absoluteKeywordLocation'])
        ptr = jschon.JSONPointer.parse_uri_fragment(s_uri.fragment)
        return s_uri.copy(fragment=ptr[:-1].uri_fragment())


class SchemaParser:
    """
    JSON Schema parser for OpenAPI description files.
    """

    @classmethod
    def get_parser(cls, config, *args, annotations=(), **kwargs):
        """
        Instantiate a parser based on the ``json schema`` config entry.

        Currently ``jshcon`` (a Python JSON Schema implementation with
        full vocabulary support) is both the default and the only
        supported implementation.

        :param config: The configuration dictionary.
        :param annotations:
        """
        if (impl := config.get('json schema', 'jschon')) != 'jschon':
            raise ValueError(
                f'Unsupported JSON Schema implementation: {impl!r}'
            )

        return JschonSchemaParser(
            config, *args, annotations=annotations, **kwargs,
        )

    def __init__(self, config, annotations=()):
        self._config = config
        self._annotations = annotations

        # Used to indicate if the implementation pre-filtered annotations.
        self._filtered = False

    def parse(self, data, oastype, output_format='basic'):
        raise NotImplementedError


class JschonSchemaParser(SchemaParser):
    def __init__(self, config, annotations=()):
        super().__init__(config, annotations)
        self._filtered = True

    def parse(self, document, oastype, output_format='basic'):
        if document.oas_root is None:
            raise ValueError(
                f"Cannot validate non-OAS node <{document.pointer_uri}>, "
                f"type {type(document).__name__}"
            )

        if document.oas_root.pointer_uri in self._result_cache:
            logger.warning(
                f'Requested re-validation of <{document.oas_root.pointer_uri}> '
                f'for <{document.pointer_uri}>, returning from cache',
            )
            return self._result_cache[document.oas_root.pointer_uri]

        # auto-creating non-Metaschema metadocuments requires
        # more work, so for now evaluate this as a "normal" schema
        # result = document.validate()
        schema = document.catalog.get_schema(document.oas_root.metadocument_uri)
        logger.info(
            f'Validating <{document.oas_root.pointer_uri}> '
            f'against <{schema.pointer_uri}>',
        )
        schema.resolve_references()
        result = schema.evaluate(document.oas_root)
        if not result.valid:
            raise JsonSchemaParseError(result.output('basic'))

        output = result.output(
            output_format,
            annotations=self._annotations,
        )
        return output
