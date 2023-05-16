from jschon import JSON, JSONCompatible, Result, URI
from jschon.catalog import Catalog
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
)

__all__ = [
    'initialize_oas30_dialect',
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

OAS30_SUBSET_VOCAB = "https://spec.openapis.org/oas/v3.0/vocab/draft-04-subset"
OAS30_EXTENSION_VOCAB = "https://spec.openapis.org/oas/v3.0/vocab/extension"
OAS30_DIALECT_METASCHEMA = "https://spec.openapis.org/oas/v3.0/dialect/base"


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


# TODO: Something better than this workaround where we consider
#       "components" and "schemas" to be keywords and splice the
#       /componenets/schemas tree into the schema excepts used
#       to validate examples and defaults.
#
#       Currently jschon does not support
#       objects-of-objects-of-schemas, although it will need to
#       for "propertyDependencies" and I have part of that
#       written for submission as a PR.
class ComponentsKeyword(Keyword, Subschema):
    key = 'components'
    static = True


class SchemasKeyword(Keyword, ObjectOfSubschemas):
    key = 'schemas'
    static = True


# NOTE: This RFC 3339 implementation does not support "duration"
@format_validator('date')
def validate_relative_json_pointer(value: str) -> None:
    if isinstance(value, str):
        # rfc3339 already raises ValueError on error
        rfc3339.parse_date(value)


@format_validator('time')
def validate_relative_json_pointer(value: str) -> None:
    if isinstance(value, str):
        # rfc3339 already raises ValueError on error
        rfc3339.parse_time(value)


@format_validator('date-time')
def validate_relative_json_pointer(value: str) -> None:
    if isinstance(value, str):
        # rfc3339 already raises ValueError on error
        rfc3339.parse_datetime(value)


# NOTE: 'json-pointer' format vaidation included in jschon.formats
@format_validator('relative-json-pointer')
def validate_relative_json_pointer(value: str) -> None:
    if isinstance(value, str):
        if not RelativeJSONPointer._regex.fullmatch(value):
            raise ValueError


@format_validator('json-pointer-template')
def validate_relative_json_pointer(value: str) -> None:
    if isinstance(value, str):
        if not JSON_POINTER_TEMPLATE.fullmatch(value):
            raise ValueError


@format_validator('relative-json-pointer-template')
def validate_relative_json_pointer(value: str) -> None:
    if isinstance(value, str):
        if not RELATIVE_JSON_POINTER_TEMPLATE.fullmatch(value):
            raise ValueError


@format_validator('uri')
def validate_uri(value: str) -> None:
    if isinstance(value, str):
        # parse() already raises a ValueError on error
        rfc3987.parse(value, rule='URI')


@format_validator('uri-reference')
def validate_uri_reference(value: str) -> None:
    if isinstance(value, str):
        # parse() already raises a ValueError on error
        rfc3987.parse(value, rule='URI_reference')


@format_validator('iri')
def validate_iri(value: str) -> None:
    if isinstance(value, str):
        # parse() already raises a ValueError on error
        rfc3987.parse(value, rule='IRI')


@format_validator('iri-reference')
def validate_iri_reference(value: str) -> None:
    if isinstance(value, str):
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
    catalog.create_vocabulary(
        URI("https://spec.openapis.org/oas/v3.0/vocab/workaround"),
        ComponentsKeyword,
        SchemasKeyword,
    )
    catalog.create_metaschema(
        URI("https://spec.openapis.org/oas/v3.0/dialect/base"),
        URI('https://json-schema.org/draft/2020-12/vocab/core'),
        URI(OAS30_SUBSET_VOCAB),
        URI(OAS30_EXTENSION_VOCAB),
        URI("https://spec.openapis.org/oas/v3.0/vocab/workaround"),
    )
    # NOTE: All strings are valid CommonMark, so the "commonmark"
    #       format is not validated.
    catalog.enable_formats(
        'date',
        'time',
        'date-time',
        'json-pointer',
        'relative-json-pointer',
        'json-pointer-template',
        'relative-json-pointer-template',
        'uri',
        'uri-reference',
        'iri',
        'iri-reference',
    )
