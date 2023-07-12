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

from oascomply.oasgraph import OasGraph
import oascomply.resourceid as rid

__all__ = [
    'Annotation',
    'SchemaParser',
]

logger = logging.getLogger(__name__)


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
            if isinstance(base, rid.IriWithJsonPtr):
                return base
            else:
                return rid.IriWithJsonPtr(str(base))
        try:
            return cls._default_instance_base
        except AttributeError:
            # NOTE: This ony works if there is only one instance document.
            # TODO: Guard against messing it up?  Do we even need this?
            cls._dibu = rid.Iri(f'urn:uuid:{uuid4()}')
        return cls._default_instance_base

    @classmethod
    def get(cls, unit: dict, instance_base: Union[str, rid.Iri] = None):
        eval_ptr = rid.JsonPtr(unit['keywordLocation'])[:-1]

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
            rid.JsonPtr(unit['keywordLocation'])[:-1] if eval_ptr is None
            else eval_ptr
        )

    def __hash__(self):
        return hash((self._instance_uri, self._eval_ptr))

    def __repr__(self):
        return 'Location(' + repr({
            'instance': str(self.instance_uri),
            'schema': str(self.schema_uri),
            'evaluationPath': str(self.evaluation_path_ptr),
        }) + ')'

    @cached_property
    def instance_resource_uri(self) -> rid.Iri:
        return self._get_instance_base_uri(self._given_base).copy(
            rid.IriWithJsonPtr
        )

    @cached_property
    def instance_uri(self) -> rid.Iri:
        return self.instance_resource_uri.copy(
            fragment=self.instance_ptr.uri_fragment(),
        )

    @cached_property
    def instance_ptr(self) -> rid.JsonPtr:
        return rid.JsonPtr(self._unit['instanceLocation'])

    @cached_property
    def evaluation_path_ptr(self) -> rid.JsonPtr:
        return self._eval_ptr

    @cached_property
    def schema_resource_uri(self) -> rid.Iri:
        return self.schema_uri.to_absolute()

    @cached_property
    def schema_uri(self) -> rid.Iri:
        s_uri = rid.IriWithJsonPtr(self._unit['absoluteKeywordLocation'])
        return s_uri.copy(fragment=s_uri.fragment_ptr[:-1].uri_fragment())


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
        with open(
            Path(__file__).parent /
                '..' /
                'schemas' /
                'oas' /
                'v3.0' /
                'schema.json',
            encoding='utf-8',
        ) as schema_fp:
            self._v30_schema = jschon.JSONSchema(
                json.load(schema_fp),
                catalog='oascomply',
            )

    def parse(self, data, oastype, output_format='basic'):
        schema = self._v30_schema
        if oastype != 'OpenAPI':
            try:
                # TODO: This probably won't work for 3.1
                schema = schema['$defs'][oastype]
            except KeyError:
                logger.error("Can't find schema for oastype {oastype!r}")
                # TODO: Better error handling
                raise

        # logger.error('\n\n\nDATA:\n' + str(data))
        # logger.error('\n\nSCHEMA:\n' + str(schema.uri))
        result = schema.evaluate(data)
        if not result.valid:
            raise JsonSchemaParseError(result.output('detailed'))

        return result.output(
            output_format,
            annotations=self._annotations,
        )
