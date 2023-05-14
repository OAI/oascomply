import json
from pathlib import Path
from uuid import uuid4
from typing import Any, Optional
import logging

import jschon
import rdflib
from rdflib.namespace import RDF
import yaml

from oascomply.oasgraph import OasGraph

__all__ = [
    'Annotation',
    'SchemaParser',
]

logger = logging.getLogger(__name__)


class Annotation:
    def __init__(self, unit, instance_base=None):
        self._location = Location.get(unit, instance_base)
        self._keyword = unit['keywordLocation'][
            unit['keywordLocation'].rindex('/') + 1:
        ]
        self._value = unit['annotation']

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
    def _instance_base_uri(cls, base=None):
        if base:
            return base
        try:
            return cls._dibu
        except AttributeError:
            cls._dibu = f'urn:uuid:{uuid4()}'
        return cls._dibu

    @classmethod
    def _eval_ptr(cls, unit):
        kl = unit['keywordLocation']
        return kl[:kl.rindex('/')]

    @classmethod
    def get(cls, unit: dict, instance_base: str=None):
        ep = cls._eval_ptr(unit)
        cache_key = (
            cls._instance_base_uri(instance_base),
            unit['instanceLocation'],
            ep,
        )
        try:
            return cls._cache[cache_key]
        except KeyError:
            l = Location(unit, eval_ptr=ep, instance_base=instance_base)
            cls._cache[cache_key] = l
            return l

    def __init__(
        self,
        unit,
        *,
        eval_ptr,
        instance_base=None
    ):
        self._instance_base = self._instance_base_uri(instance_base)
        self._eval_ptr = eval_ptr

        self._instance_resource_uri = jschon.URI(self._instance_base)
        self._instance_ptr = jschon.JSONPointer(unit['instanceLocation'])
        self._instance_uri = self._instance_resource_uri.copy(
            fragment=self._instance_ptr.uri_fragment(),
        )

        akl = unit['absoluteKeywordLocation']
        # construct, splice off last JSON Pointer
        self._schema_uri = jschon.URI(akl[:akl.rindex('/')])
        self._schema_resource_uri = jschon.URI(akl[:akl.rindex('#')])

        # extract JSON Pointer
        self._schema_ptr = jschon.JSONPointer.parse_uri_fragment(
            self._schema_uri.fragment
        )

        keyword_uri = jschon.URI(akl)
        schema_keyword_ptr = jschon.JSONPointer.parse_uri_fragment(
            keyword_uri.fragment,
        )
        self._schema_uri = keyword_uri.copy(
            fragment=schema_keyword_ptr[:-1].uri_fragment(),
        )
        # remove fragment
        self._schema_resource_uri = keyword_uri.copy(fragment=None)

    def __hash__(self):
        return hash((self._instance_uri, self._eval_ptr))

    @property
    def instance_resource_uri(self):
        return self._instance_resource_uri

    @property
    def instance_uri(self):
        return self._instance_uri

    @property
    def instance_ptr(self):
        return self._instance_ptr

    @property
    def evaluation_path_ptr(self):
        return self._eval_ptr

    @property
    def schema_resource_uri(self):
        return self._schema_resource_uri

    @property
    def schema_uri(self):
        return self._schema_uri

    @property
    def schema_keyword_ptr(self):
        return self._schema_keyword_ptr

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
            self._v30_schema = jschon.JSONSchema(json.load(schema_fp))

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

        result = schema.evaluate(data)
        if not result.valid:
            logger.critical(
                "Schema validation failed!\n\n" +
                json.dumps(result.output('detailed'), indent=2)
            )
            # TODO: better exit strategy
            raise Exception("Schema vaidation failed!")

        return result.output(
            output_format,
            annotations=self._annotations,
        )