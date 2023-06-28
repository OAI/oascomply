import re
import logging
from collections import defaultdict
from typing import Union

from jschon import JSON, JSONCompatible, JSONSchema, Result, URI
from jschon.catalog import Catalog, CatalogError
from jschon.jsonpointer import RelativeJSONPointer
from jschon.vocabulary.format import format_validator
from jschon.vocabulary import (
    Keyword, KeywordClass, Metaschema, ObjectOfSubschemas, Subschema,
    Vocabulary, format as format_, annotation, applicator, validation,
)

import rfc3339
import rfc3987

from oascomply.ptrtemplates import (
    JSON_POINTER_TEMPLATE, RELATIVE_JSON_POINTER_TEMPLATE,
    RelJsonPtrTemplate,
)
import oascomply.resourceid as rid

__all__ = [
    'initialize_oas30_dialect',
    'OaJson',
    'OAS30_SUBSET_VOCAB',
    'OAS30_EXTENSION_VOCAB',
    'OAS30_DIALECT_METASCHEMA',
    'DiscriminatorKeyword',
    'ExampleKeyword',
    'ExternalDocsKeyword',
    'NullableKeyword',
    'XmlKeyword',
    'Oas30ExclusiveMaximumKeyword',
    'Oas30ExclusiveMinimumKeyword',
]

logger = logging.getLogger(__name__)

OAS30_SUBSET_VOCAB = "https://spec.openapis.org/oas/v3.0/vocab/draft-04-subset"
OAS30_EXTENSION_VOCAB = "https://spec.openapis.org/oas/v3.0/vocab/extension"
OAS30_DIALECT_METASCHEMA = "https://spec.openapis.org/oas/v3.0/dialect/base"


class OasJsonError(Exception):
    """Base class for errors raised by :class:`OasJson`"""
    def __str__(self):
        return self.args[0]


class OasJsonTypeError(OasJsonError, TypeError):
    """Indicates an attempt to treat an OasJson as a jschon.JSONSchema"""
    def __init__(self, uri, url):
        super().__init__('Cannot evaluate OasJson as JSONSchema', uri, url)

    @property
    def uri(self):
        """The URI of the mis-typed resource (possiby same as the URL)"""
        return self.args[1]

    @property
    def url(self):
        """The URL of the mis-typed resource"""
        return self.args[2]


class OasJsonUnresolvableRefError(OasJsonError, ValueError):
    """Indicates that a reference target could not be found."""
    def __init__(self, ref_uri):
        super().__init__(
            f"Could not resolve reference to {ref_uri}",
            ref_uri,
        )

    @property
    def ref_uri(self):
        return self.args[1]


class OasJsonRefSuffixError(OasJsonError, ValueError):
    """Indicates misuse of filesystem suffixes in retrieving a resource."""
    def __init__(
        self,
        source_schema_uri,
        ref_uri,
        ref_resource_uri,
        target_resource_uri,
        suffix,
    ):
        super().__init__(
            f"Reference without suffix attempted despite target resource "
            f"being registered under a URI with suffix",
            source_schema_uri,
            ref_uri,
            ref_resource_uri,
            target_resource_uri,
            suffix,
        )

    @property
    def source_schema_uri(self):
        return self.args[1]

    @property
    def ref_uri(self):
        return self.args[2]

    @property
    def ref_resource_uri(self):
        return self.args[3]

    @property
    def target_resource_uri(self):
        return self.args[4]

    @property
    def suffix(self):
        return self.args[5]


# NOTE: This depends on the changes proposed in jschon PR #101,
#       currently available through the git repository as shown
#       in pyproject.toml.
class OasJson(JSON):
    """Representation of an OAS document based on :class:`jschon.json.JSON`"""
    def __init__(
        self,
        value,
        *,
        uri=None,
        url=None,
        parent=None,
        key=None,
        itemclass=None,
        catalog='catalog',
        cacheid='default',
        **itemkwargs,
    ):
        if 'oasversion' not in itemkwargs:
            if 'openapi' not in value:
                raise ValueError(
                    f"{type(self)} requires the 'openapi' field "
                    "or an 'oasversion' constructor parameter",
                )

            # Chop off patch version number
            itemkwargs['oasversion'] = value['openapi'][:3]

        if 'oas_metaschema_uri' not in itemkwargs:
            if itemkwargs['oasversion'] == '3.1':
                itemkwargs['oas_metaschema_uri'] = URI(value.get(
                    'jsonSchemaDialect',
                    "https://spec.openapis.org/oas/3.1/dialect/base",
                ))
            elif itemkwargs['oasversion'] == '3.0':
                itemkwargs['oas_metaschema_uri'] = URI(
                    "https://spec.openapis.org/oas/v3.0/dialect/base",
                )
            else:
                raise ValueError(
                    f"Unsupported OAS version {value['openapi']}",
                )
        self._oas_metaschema_uri = itemkwargs['oas_metaschema_uri']
        self._oasversion = itemkwargs['oasversion']

        self.uri = uri if isinstance(
            uri, rid.UriWithJsonPtr
        ) else rid.UriWithJsonPtr(str(uri))
        self.url = url if isinstance(
            url, rid.UriWithJsonPtr
        ) else rid.UriWithJsonPtr(str(url))

        if not isinstance(catalog, Catalog):
            catalog = Catalog.get_catalog(catalog)

        # Track position with JSON Pointer fragments, so ensure we have one
        # TODO: Sometimes we don't want an empty fragment on the root document.
        if not self.uri.fragment:
            if self.uri.fragment is None:
                catalog.add_schema(URI(str(self.uri)), self, cacheid=cacheid)
                self.uri = self.uri.copy_with(fragment='')
            else:
                catalog.add_schema(
                    URI(str(self.uri.to_absolute())),
                    self,
                    cacheid=cacheid,
                )
        if not self.url.fragment:
            self.url = self.url.copy_with(fragment='')

        self._schemakwargs = itemkwargs.copy()
        del self._schemakwargs['oasversion']
        del self._schemakwargs['oas_metaschema_uri']
        self._schemakwargs['catalog'] = catalog
        self._schemakwargs['cacheid'] = cacheid
        self._value = value

        self._to_resolve = []
        super().__init__(
            value,
            parent=parent,
            key=key,
            **itemkwargs,
        )

    def instantiate_mapping(self, value):
        schema_constructor = (
            # Note that we intentionally replace kwargs with self._schemakwargs
            lambda v, parent, key, uri, **kwargs: JSONSchema(
                v,
                parent=parent,
                key=key,
                uri=URI(str(uri)),
                metaschema_uri=self._oas_metaschema_uri,
                **self._schemakwargs,
            )
        )
        if str(self.path) == '/components/schemas':
            classes = defaultdict(lambda: schema_constructor)
        elif self.path and self.path[-1] == 'examples':
            classes = defaultdict(lambda: JSON)
        else:
            classes = defaultdict(lambda: type(self))
            classes['schema'] = schema_constructor
            classes['example'] = JSON
            classes['default'] = JSON
            classes['enum'] = JSON

        mapping = {}
        for k, v in value.items():
            mapping[k] = classes[k](
                v,
                parent=self,
                key=k,
                uri=self.uri.copy_with(fragment=self.uri.fragment / k),
                url=self.url.copy_with(fragment=self.url.fragment / k),
                **self.itemkwargs,
            )
            if isinstance(mapping[k], JSONSchema):
                root = self
                while root.parent is not None:
                    root = root.parent
                root._to_resolve.append(mapping[k])
        return mapping

    def resolve_references(self):
        for schema in self._to_resolve:
            if not isinstance(schema, JSONSchema):
                if isinstance(schema, OasJson):
                    # TODO: manage empty fragments better in general
                    # TODO: duplication with other raise OasJsonTypeError
                    uri = self.uri.copy_with(
                        fragment=None,
                    ) if self.uri.fragment == '' else self.uri
                    url = self.url.copy_with(
                        fragment=None,
                    ) if self.url.fragment == '' else self.url
                    raise OasJsonTypeError(uri=uri, url=url)
            try:
                schema._resolve_references()
            except CatalogError as e:
                import re
                if m := re.search(
                    'source is not available for "([^"]*)"',
                    str(e),
                ):
                    ref_uri = rid.Iri(m.groups()[0])
                    ref_resource_uri = ref_uri.to_absolute()
                    logger.warning(
                        f'Could not load referenced schema {ref_uri}, '
                        'checking for common configuration errors...',
                    )
                    for suffix in ('.json', '.yaml', '.yml'):
                        uri_with_suffix = f'{ref_resource_uri}{suffix}'
                        try:
                            if ref_schema := schema.catalog.get_schema(
                                URI(uri_with_suffix),
                                cacheid=schema.cacheid,
                            ):
                                raise OasJsonRefSuffixError(
                                    source_schema_uri=rid.Iri(
                                        str(schema.uri)
                                    ),
                                    ref_uri=ref_uri,
                                    ref_resource_uri=ref_resource_uri,
                                    target_resource_uri=rid.Iri(
                                        uri_with_suffix
                                    ),
                                    suffix=suffix,
                                ) from e
                        except CatalogError:
                            pass
                    raise OasJsonUnresolvableRefError(ref_uri)

                elif m := re.search(' ([^ ]*) is not a JSON Schema', str(e)):
                    uri = rid.Iri(m.groups()[0]).copy_with(
                        fragment=None,
                    ) if self.uri.fragment == '' else self.uri
                    url = None # self.url.copy_with(
                    #     fragment=None,
                    # ) if self.url.fragment == '' else self.url
                    raise OasJsonTypeError(uri=uri, url=url) from e
                raise

    def evaluate(self, instance: JSON, result: Result = None) -> Result:
        # TODO: manage empty fragments better in general
        uri = self.uri.copy_with(
            fragment=None,
        ) if self.uri.fragment == '' else self.uri
        url = self.url.copy_with(
            fragment=None,
        ) if self.url.fragment == '' else self.url
        raise OasJsonTypeError(uri=uri, url=url)


class _OasAnnotationKeyword(Keyword):
    def evaluate(self, instance: JSON, result: Result) -> None:
        result.annotate(self.json.value)
        result.noassert()


class DiscriminatorKeyword(Keyword):
    key = 'discriminator'

    def evaluate(self, instance: JSON, result: Result) -> None:
        value = self.json.value
        result.annotate(value)
        if value['propertyName'] not in instance:
            result.fail(
                f"Property {value['propertyName']} required by discriminator"
            )


class ExampleKeyword(_OasAnnotationKeyword):
    key = 'example'


class ExternalDocsKeyword(_OasAnnotationKeyword):
    key = 'externalDocs'


class NullableKeyword(Keyword):
    key = 'nullable'
    depends_on = 'type',

    def evaluate(self, instance: JSON, result: Result) -> None:
        if self.json.value is False and instance.value is None:
            result.fail('Cannot have null instance with "nullable": false')
        elif self.json.value is True and (
            type_result := result.sibling(instance, "type")
        ):
            if instance.value is None and not type_result.valid:
                type_result.pass_()


class XmlKeyword(_OasAnnotationKeyword):
    key = 'xml'


class Oas30ExclusiveMaximumKeyword(Keyword):
    key = 'exclusiveMaximum'
    depends_on = 'maximum',

    def evaluate(self, instance: JSON, result: Result) -> None:
        if (
            (max_result := result.sibing(instance, "maximum")) and
            max_result.valid
        ):
            maximum == result.schema['maximum'].value
            if instance.value == maximum:
                result.fail(
                    f"The value must be less than {maximum}"
                )


class Oas30ExclusiveMinimumKeyword(Keyword):
    key = 'exclusiveMinimum'
    depends_on = 'minimum',

    def evaluate(self, instance: JSON, result: Result) -> None:
        if (
            (min_result := result.sibing(instance, "minimum")) and
            min_result.valid
        ):
            minimum == result.schema['minimum'].value
            if instance.value == minimum:
                result.fail(
                    f"The value must be greater than {minimum}"
                )


@format_validator('uint8', instance_types=('number',))
def validate_uint8(value: Union[int, float]):
    if value % 1:
        raise ValueError(f'{value} is not an integer')
    if value < 0 or value > 255:
        raise ValueError(f'{value} is outside of uint8 range')


@format_validator('uint16', instance_types=('number',))
def validate_uint16(value: Union[int, float]):
    if value % 1:
        raise ValueError(f'{value} is not an integer')
    if value < 0 or value > 65535:
        raise ValueError(f'{value} is outside of uint16 range')


@format_validator('uint32', instance_types=('number',))
def validate_uint32(value: Union[int, float]):
    if value % 1:
        raise ValueError(f'{value} is not an integer')
    if value < 0 or value > 4294967295:
        raise ValueError(f'{value} is outside of uint32 range')


@format_validator('uint64', instance_types=('number', 'string'))
def validate_uint64(value: Union[int, float, str]):
    if isinstance(value, str):
        if set(value) - set('0123456789'):
            raise ValueError("{value!r} is not an integer string")
        value = int(value)
    if value % 1:
        raise ValueError(f'{value} is not an integer')
    if value < 0 or value > 18446744073709551615:
        raise ValueError(f'{value} is outside of uint64 range')


@format_validator('int8', instance_types=('number',))
def validate_int8(value: Union[int, float]):
    if value % 1:
        raise ValueError(f'{value} is not an integer')
    if value < -128 or value > 127:
        raise ValueError(f'{value} is outside of int8 range')


@format_validator('int16', instance_types=('number',))
def validate_int16(value: Union[int, float]):
    if value % 1:
        raise ValueError(f'{value} is not an integer')
    if value < -32768 or value > 32767:
        raise ValueError(f'{value} is outside of int16 range')


@format_validator('int32', instance_types=('number',))
def validate_int32(value: Union[int, float]):
    if value % 1:
        raise ValueError(f'{value} is not an integer')
    if value < -2147483648 or value > 2147483647:
        raise ValueError(f'{value} is outside of int32 range')


@format_validator('int64', instance_types=('number', 'string'))
def validate_int64(value: Union[int, float, str]):
    if isinstance(str):
        if set(value) - set('0123456789'):
            raise ValueError("{value!r} is not an integer string")
        value = int(value)
    if value % 1:
        raise ValueError(f'{value} is not an integer')
    if value < -9223372036854775808 or value > 9223372036854775807:
        raise ValueError(f'{value} is outside of int64 range')


# NOTE: This RFC 3339 implementation does not support "duration"
@format_validator('date', instance_types=('string',))
def validate_relative_json_pointer(value: str) -> None:
    # rfc3339 already raises ValueError on error
    rfc3339.parse_date(value)


@format_validator('time', instance_types=('string',))
def validate_relative_json_pointer(value: str) -> None:
    # rfc3339 already raises ValueError on error
    rfc3339.parse_time(value)


@format_validator('date-time', instance_types=('string',))
def validate_relative_json_pointer(value: str) -> None:
    # rfc3339 already raises ValueError on error
    rfc3339.parse_datetime(value)


# NOTE: 'json-pointer' format vaidation included in jschon.formats
@format_validator('relative-json-pointer', instance_types=('string',))
def validate_relative_json_pointer(value: str) -> None:
    if not re.fullmatch(RelativeJSONPointer._regex, value):
        raise ValueError


@format_validator('json-pointer-template', instance_types=('string',))
def validate_relative_json_pointer(value: str) -> None:
    if not re.fullmatch(JSON_POINTER_TEMPLATE, value):
        raise ValueError


@format_validator('relative-json-pointer-template', instance_types=('string',))
def validate_relative_json_pointer(value: str) -> None:
    RelJsonPtrTemplate(value)
    if not re.fullmatch(RELATIVE_JSON_POINTER_TEMPLATE, value):
        raise ValueError


@format_validator('uri', instance_types=('string',))
def validate_uri(value: str) -> None:
    # parse() already raises a ValueError on error
    rfc3987.parse(value, rule='URI')


@format_validator('uri-reference', instance_types=('string',))
def validate_uri_reference(value: str) -> None:
    # parse() already raises a ValueError on error
    rfc3987.parse(value, rule='URI_reference')


@format_validator('iri', instance_types=('string',))
def validate_iri(value: str) -> None:
    # parse() already raises a ValueError on error
    rfc3987.parse(value, rule='IRI')


@format_validator('iri-reference', instance_types=('string',))
def validate_iri_reference(value: str) -> None:
    # parse() already raises a ValueError on error
    rfc3987.parse(value, rule='IRI_reference')


def initialize_oas30_dialect(catalog: Catalog):
    catalog.create_vocabulary(
        URI(OAS30_SUBSET_VOCAB),
        annotation.TitleKeyword,
        annotation.DescriptionKeyword,
        annotation.DefaultKeyword,
        applicator.AllOfKeyword,
        applicator.AnyOfKeyword,
        applicator.OneOfKeyword,
        applicator.NotKeyword,
        applicator.ItemsKeyword,  # 2020-12 "items" syntax matches OAS 3.0
        applicator.PropertiesKeyword,
        applicator.AdditionalPropertiesKeyword,
        validation.TypeKeyword,
        validation.EnumKeyword,
        validation.MultipleOfKeyword,
        validation.MaximumKeyword,
        Oas30ExclusiveMaximumKeyword,
        validation.MinimumKeyword,
        Oas30ExclusiveMinimumKeyword,
        validation.MaxLengthKeyword,
        validation.MinLengthKeyword,
        validation.PatternKeyword,
        validation.MaxItemsKeyword,
        validation.MinItemsKeyword,
        validation.UniqueItemsKeyword,
        validation.MaxPropertiesKeyword,
        validation.MinPropertiesKeyword,
        validation.RequiredKeyword,
        format_.FormatKeyword,
    )
    catalog.create_vocabulary(
        URI(OAS30_EXTENSION_VOCAB),
        annotation.DeprecatedKeyword,
        annotation.ReadOnlyKeyword,
        annotation.WriteOnlyKeyword,
        DiscriminatorKeyword,
        ExampleKeyword,
        ExternalDocsKeyword,
        NullableKeyword,
        XmlKeyword,
    )
    catalog.create_metaschema(
        URI("https://spec.openapis.org/oas/v3.0/dialect/base"),
        URI('https://json-schema.org/draft/2020-12/vocab/core'),
        URI(OAS30_SUBSET_VOCAB),
        URI(OAS30_EXTENSION_VOCAB),
    )
    # NOTE: All strings are valid CommonMark, so the "commonmark"
    #       format is not validated.
    catalog.enable_formats(
        'uint8', 'uint16', 'uint32', 'uint64',
        'int8', 'int16', 'int32', 'int64',
        'date', 'time', 'date-time',
        'json-pointer', 'relative-json-pointer',
        'json-pointer-template', 'relative-json-pointer-template',
        'uri', 'uri-reference', 'iri', 'iri-reference',
    )


def validate_with_oas30():
    import sys
    import argparse
    import yaml
    import json

    parser = argparse.ArgumentParser(
        description='Validates the instance against schemas using the '
                    'OAS 3.0 Schema Object dialect described by the '
                    'metaschema "{OAS30_DIALECT_METASCHEMA}"',
        epilog=f'Note that the schema "{OAS30_DIALECT_METASCHEMA}" is '
                '*NOT* provided by the OpenAPI Initiative, but is part of the '
                'oascomply package (oascomply.schemas/oas/v3.0/base.json)',
        fromfile_prefix_chars='@',
    )
    parser.add_argument(
        'instance',
        help='The JSON or YAML file to validate',
    )
    parser.add_argument(
        'schema',
        help='The schema, in JSON or YAML format, to use',
    )
    parser.add_argument(
        '-r',
        '--referenced-schema',
        action='append',
        dest='refs',
        default=[],
        help='NOT YET SUPPORTED! '
             'An additional schema from which to resolve references; '
             'can be passed multiple times; note that schema documents '
             'that reference each other are not currently supported; '
             'currently, if schema A references schema B, then schema B '
             'must be passed with -r *BEFORE* schema A',
    )
    parser.add_argument(
        '-o',
        '--output',
        choices=('basic', 'detailed', 'verbose'),
        nargs='?',
        const='basic',
        help='On success, print the annotation output to stdout using '
             'the given standard format; the default annotation format '
             "is 'basic'",
    )
    parser.add_argument(
        '-e',
        '--error-format',
        choices=('basic', 'detailed', 'verbose'),
        default='detailed',
        help='Set the output format to use for error reporting; the '
             "default format is 'detailed'",
    )

    args = parser.parse_args()
    metaschema_uri = URI(OAS30_DIALECT_METASCHEMA)
    metaschema_errors = {}

    # TODO: Actually detect and parse json properly
    sys.stderr.write(f'Loading instance {args.instance}...\n')
    with open(args.instance) as inst_fd:
        instance = JSON(yaml.safe_load(inst_fd))

    # TODO: Be more forgiving about the load order of refschemas,
    #       as this means that a schema can only a reference another
    #       schema that has already been loaded
    for ref in args.refs:
        # Constructing a JSONSchema registers it with the Catalog
        sys.stderr.write(f'Loading ref schema {ref}...\n')
        with open(ref) as ref_fd:
            ref_schema = JSONSchema(
                yaml.safe_load(ref_fd),
                metaschema_uri=metaschema_uri,
            )
            meta_result = ref_schema.validate()
            if not meta_result.valid:
                metaschema_errors[ref] = meta_result

    sys.stderr.write(f'Loading schema {args.schema}...\n')
    with open(args.schema) as schema_fd:
        schema = JSONSchema(
            yaml.safe_load(schema_fd),
            metaschema_uri=metaschema_uri,
        )
        meta_result = schema.validate()
        if not meta_result.valid:
            metaschema_errors[args.schema] = meta_result

    if metaschema_errors:
        for path, meta_result in metaschema_errors.items():
            sys.stderr.write(
                f'OAS 3.0 metaschema validation failed for {args.schema}!\n',
            )
            json.dump(
                meta_result.output(args.error_format),
                sys.stderr,
                indent=2,
            )
            sys.stderr.write('\n\n')
        sys.exit(-1)

    sys.stderr.write('Evaluating the instance against the schema...\n')
    result = schema.evaluate(instance)
    if result.valid:
        sys.stderr.write('Your instance is valid!\n')
        if args.output:
            json.dump(result.output(args.output), sys.stdout, indent=2)
            sys.stdout.write('\n')
    else:
        sys.stderr.write('Schema validation failed!\n')
        json.dump(result.output(args.error_format), sys.stderr, indent=2)
        sys.stderr.write('\n')
