from jschon import create_catalog, JSON, JSONPointer, URI
from uuid import uuid4

import rdflib
from rdflib.namespaces import RDF

__all__ = [
    'SchemaParser',
]

class OasParser:

    def __init__(self, *documents):
        # load documents
        # determine or assign URIs
        # load schema
        # set everything up to be referenced w/URIs and/or JSON Pointers

class OasGraph:
    def __init__(self, version):
        if version not in ('3.0', '3.1'):
            raise ValueError(f'OAS v{version} is not supported.')
        if version == '3.1':
            raise ValueError(f'OAS v3.1 support TBD.')

        self._g = rdflib.Graph()
        self._oas = rdf.lib.Namespace(
            f'https://spec.openapis.org/oas/v{version}/ontology#'
        )


    def add_type(self, typename, location):
        instance_loc = rdflib.URIRef(location.instance_uri.unsplit())
        self._g.add((
            instance_loc,
            RDF.type
            self._oas[typename],
        ))
        self._g.add((
            instance_loc,
            RDF.type,
            self._oas['ParsedStructure'],
        ))

    def link_parents(self):
        


class Location:
    @classmethod
    def default_instance_base_uri(cls):
        try:
            return cls._dibu
        except AttributeError:
            cls._dibu = URI(f'urn:uuid:{uuid4()}') 
        return cls._dibu

    def __init__(
        self,
        *,
        basic_unit=None,
        list_unit=None,
        instance_base=None,
    ):
        # TODO: "list" output unit support
        if basic_unit is None:
            if list_unit is None:
                raise ValueError(
                    "Must supply either 'basic_unit' or 'list_unit'"
                )
            else:
                raise NotImplementedError("'list' output not yet supported")
            
        unit = dr

        self._instance_resource_uri = (
            self.default_instance_base_uri if instance_base is None else
            URI(instance_base)
        )
        # We can use jschon's JSONPointer with any schema implementation
        self._instance_ptr = JSONPointer(unit['instanceLocation'])
        self._instance_uri = self._instance_resource_uri.copy_with(
            fragment=self._instance_ptr.uri_fragment
        )

        # To find the evaluation path and schema location, we need
        # to strip off the last JSON Pointer segment of keywordLocation
        # and absoluteKeywordLocation, respectively.
        self._keyword_eval_ptr = JSONPointer(unit['keywordLocation'])
        self._eval_ptr = self._eval_keyword_ptr[:-1]
        self._keyword = self._eval_keyword_ptr[-1]

        self._keyword_uri = URI(unit['absoluteKeywordLocation'])
        self._schema_keyword_ptr = JSONPointer.parse_uri_fragment(
            self._keyword_uri.fragment,
        )
        self._schema_uri = akl_uri.copy(
            fragment=schema_keyword_ptr[:-1].uri_fragment(),
        )
        self._schema_resource_uri = self.keyword_uri.copy_with(fragment=None)

    def __hash__(self):
        return (self._instance_uri, self._eval_keyword_ptr

    @property
    def instance_ptr(self):
        return self._instance_ptr

    @property
    def keyword(self):
        return self._keyword

    @property
    def keyword_evaluation_ptr(self):
        return self._keyword_eval_ptr

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

            loc = Location(basic_unit=unit)

            if keyword == 'oasType':

            entry = new_output
            for segment in instance_ptr:
                entry = entry.setdefault(segment, {})

            entry['instanceLocation'] = unit['instanceLocation']
            entry['schemaLocation'] = str(schema_uri)


class JschonSchemaParser(SchemaParser):
    _catalog = create_catalog('2020-12')

    def __init__(self, config, annotations=()):
        super.__init__(config, annotations)
        self._filtered = True
        for base, path in config['schema directories'].items():
            self._catalog.add_uri_source(base, path)

    def parse(self, schema_uri, desc_data, output_format='basic'):
        schema = self._catalog.get_schema(URI(schema_uri))
        instance = JSON(desc_data)
        result = schema.evaluate(instance)
        return result.output(output_format, self._annotations)
