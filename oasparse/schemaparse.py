import json
from pathlib import Path
from uuid import uuid4

from jschon import (
    create_catalog, JSON, JSONSchema, URI,
    JSONPointer, RelativeJSONPointer, RelativeJSONPointerError,
)
import rdflib
from rdflib.namespace import RDF
import yaml

__all__ = [
    'SchemaParser',
]

class OasParser:

    def __init__(self, *documents):
        # load documents
        # determine or assign URIs
        # load schema
        # set everything up to be referenced w/URIs and/or JSON Pointers

        self._documents = {}
        for d in documents:
            with open(d, encoding='utf-8') as d_fp:
                self._documents[f'urn:uuid:{uuid4()}'] = \
                    json.load(d_fp) if d.endswith('.json') else \
                    yaml.safe_load(d_fp)

    def parse(self):
        pass


class OasGraph:
    def __init__(self, version, base=None):
        if version not in ('3.0', '3.1'):
            raise ValueError(f'OAS v{version} is not supported.')
        if version == '3.1':
            raise ValueError(f'OAS v3.1 support TBD.')

        self._g = rdflib.Graph(base=base)
        self._oas = rdflib.Namespace(
            f'https://spec.openapis.org/oas/v{version}/ontology#'
        )
        self._g.bind('oas3.0', self._oas)

    def serialize(self, *args, **kwargs):
        return self._g.serialize(*args, **kwargs)

    def add_oastype(self, annotation, instance):
        instance_uri = rdflib.URIRef(str(annotation.location.instance_uri))
        self._g.add((
            instance_uri,
            RDF.type,
            self._oas[annotation.value],
        ))
        self._g.add((
            instance_uri,
            RDF.type,
            self._oas['ParsedStructure'],
        ))

    def add_oaschildren(self, annotation, instance):
        location = annotation.location
        parent_uri = rdflib.URIRef(str(location.instance_uri))
        for child in annotation.value:
            child = child.value
            if '{' not in child:
                child_ptr = RelativeJSONPointer(child)
                parent_obj = location.instance_ptr.evaluate(instance)
                try:
                    child_obj = child_ptr.evaluate(parent_obj)
                except RelativeJSONPointerError:
                    continue
                child_path = child_obj.path
                iu = location.instance_uri
                child_uri = rdflib.URIRef(str(iu.copy(
                    fragment=child_path.uri_fragment(),
                )))
                self._g.add((
                    parent_uri,
                    self._oas[child_ptr.path[0]],
                    child_uri,
                ))
                self._g.add((
                    child_uri,
                    self._oas['parent'],
                    parent_uri,
                ))



class Annotation:
    def __init__(self, unit, instance_base=None):
        self._location, self._keyword = Location.get(unit, instance_base)
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
    def default_instance_base_uri(cls):
        try:
            return cls._dibu
        except AttributeError:
            cls._dibu = URI(f'urn:uuid:{uuid4()}') 
        return cls._dibu

    @classmethod
    def get(cls, unit, instance_base=None):
        instance_resource_uri = (
            self.default_instance_base_uri() if instance_base is None else
            URI(instance_base)
        )

        # We can use jschon's JSONPointer with any schema implementation
        instance_ptr = JSONPointer(unit['instanceLocation'])
        instance_uri = instance_resource_uri.copy(
            fragment=instance_ptr.uri_fragment()
        )
        # To find the evaluation path and schema location, we need
        # to strip off the last JSON Pointer segment of keywordLocation
        # and absoluteKeywordLocation, respectively.
        keyword_eval_ptr = JSONPointer(unit['keywordLocation'])
        eval_ptr = keyword_eval_ptr[:-1]
        keyword = keyword_eval_ptr[-1]
        try:
            return cls._cache[(instance_uri, eval_ptr)], keyword
        except KeyError:
            l = Location(unit,
                eval_ptr=eval_ptr,
                instance_ptr=instance_ptr,
                instance_uri=instance_uri,
                instance_resource_uri=instance_resource_uri,
            )
            cls._cache[l] = l
            return l, keyword

    def __init__(
        self,
        unit,
        *,
        eval_ptr,
        instance_ptr,
        instance_uri,
        instance_resource_uri,
        instance_base=None
    ):
        self._instance_resource_uri = instance_resource_uri
        self._instance_ptr = instance_ptr
        self._instance_uri = instance_uri
        self._eval_ptr = eval_ptr


        keyword_uri = URI(unit['absoluteKeywordLocation'])
        schema_keyword_ptr = JSONPointer.parse_uri_fragment(
            keyword_uri.fragment,
        )
        self._schema_uri = keyword_uri.copy(
            fragment=schema_keyword_ptr[:-1].uri_fragment(),
        )
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
    def get_parser(config, annotations=()):
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

        return JschonSchemaParser(*args, **kwargs)

    def __init__(self, config, annotations=()):
        self._config = config
        self._annotations = annotations

        # Used to indicate if the implementation pre-filtered annotations.
        self._filtered = False

    def parse(self, schema_uri, desc_data, output_format='basic'):
        raise NotImplementedError

    def _process_output(output, output_format):
        """
        Restructure the standardized output into an instance-oriented tree.

        JSON Schema standardized output formats are either flat or organized
        by the schema evaluation path structure.  This method converts
        supported output formats (currenty only 'basic', and presumably 'list'
        when it becomes available) into tree based on instance structure.

        :param output: The standardized output from a JSON Schema implementation

        :raises ValueError: when the output format is not supported
        """
        if output_format != 'basic':
            raise ValueError(
                f'Unsupported JSON Schema output format {output_format!r}'
            )

        return _process_basic_output(output)

    def _process_basic_output(output):
        datakey = 'annotations' if output['valid'] else 'error'
        infokey = 'annotations' if output['valid'] else 'errors'

        new_output = set()
        for unit in sorted(
            output[infokey],
            lambda x: (x['instanceLocation'], x['keywordLocation']),
        ):
            if datakey not in unit:
                continue

            if (
                not self._filtered and
                datakey == 'annotations' and
                self._annotations
            ):
                if keyword not in self.annotations:
                    continue

            ann = Annotation(unit)
            # TODO: TBD


class JschonSchemaParser(SchemaParser):
    _catalog = None

    def __init__(self, config, annotations=()):
        if not self._catalog:
            self._catalog = create_catalog('2020-12')

        super.__init__(config, annotations)
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
            self._v30_schema = JSONSchema(json.load(schema_fp))

    def parse(self, schema_uri, desc_data, output_format='basic'):
        # schema = self._catalog.get_schema(URI(schema_uri))
        instance = JSON(desc_data)
        result = self._v30_schema.evaluate(instance)
        return result.output(output_format, self._annotations)

def resolve_rjp_template(instance, rjpt):
    for index, segment in enumerate(rjpt.path):
        pass

if __name__ == '__main__':
    create_catalog('2020-12')
    repo_root = (Path(__file__).parent / '..').resolve()
    with open(
        repo_root / 'schemas' / 'oas' / 'v3.0' / 'schema.json',
        encoding='utf-8',
    ) as schema_fp:
        v30_schema = JSONSchema(json.load(schema_fp))
    with open(
        repo_root / 'descriptions' / 'petstore.yaml',
        encoding='utf-8',
    ) as desc_fp:
        desc = JSON(yaml.safe_load(desc_fp))

    result = v30_schema.evaluate(desc)
    if not result.valid:
        import sys
        json.dump(result.output('detailed'), sys.stderr)
        sys.stderr.write('\n')
        sys.exit(-1)

    g = OasGraph('3.0', base=str(Location.default_instance_base_uri()))
    for unit in result.output(
        'basic',
        annotations=(
            # 'oasApiLinks',
            'oasChildren',
            # 'oasDescriptionLinks',
            # 'oasExamples',
            # 'oasExtensible',
            # 'oasImplicitReferences',
            # 'oasLiteralType',
            # 'oasLiterals',
            # 'oasReferenceConflict',
            # 'oasReferences',
            'oasType',
            # 'oasUniqueKey',
            # 'oasValues',
        )
    )['annotations']:
        ann = Annotation(
            unit,
            instance_base='https://example.com/oad/petstore'
        )
        method = f'add_{ann.keyword.lower()}'
        if hasattr(g, method):
            getattr(g, method)(ann, desc)
        else:
            import sys
            sys.stderr.write(method + '\n')
            pass

    print(g.serialize(format='turtle'))
