import sys, os.path, io, logging, json
from collections import defaultdict

from ruamel.yaml import YAML
yaml=YAML(typ='safe')

import rfc3986

import jschon, jschon.catalog
from jschon.jsonpointer import JSONPointer

import rdflib
from rdflib.namespace import RDF

from gremlin_python.process.graph_traversal import __
from gremlin_python.process.anonymous_traversal \
    import traversal as gremlin_traversal
from gremlin_python.driver.driver_remote_connection import \
    DriverRemoteConnection as GremlinRemoteConnection

from oastype4jschon import OasType, OasSubType

log = logging.getLogger('oasparse')
log.setLevel(logging.DEBUG)

# Note that you need 3.0.3 in the URI to get it to resolve.
# The analogous URI with just 3.0 does not redirect.
OAS_30_SPEC_BASE_URI = \
    rfc3986.uri_reference('https://spec.openapis.org/oas/v3.0.3')

# This is totaly arbitrary.
DOCUMENT_BASE_URI = rfc3986.uri_reference('https://example.com/oad/')

LOCAL_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEMA_DIR = os.path.join(LOCAL_DIR, '..', 'schemas')
DESC_DIR = os.path.join(LOCAL_DIR, '..', 'descriptions')

class InMemorySource(jschon.catalog.Source):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._registry = {}

    def register(self, relative_path, schema):
        self._registry[relative_path] = schema

    def __call__(self, relative_path):
        return self._registry[relative_path]

def init_jschon():
    catalog = jschon.create_catalog('2020-12')

    in_memory_source = InMemorySource()
    with \
        open(os.path.join(SCHEMA_DIR, 'meta', 'oastype.json')) as mfd, \
        open(os.path.join(SCHEMA_DIR, 'dialect', 'oastype.json')) as dfd \
    :
        in_memory_source.register('meta/2020-12/oastype', json.load(mfd))
        in_memory_source.register('dialect/2020-12/oastype', json.load(dfd))

    catalog.add_uri_source(
        jschon.URI('https://spec.openapis.org/reference/'),
        in_memory_source,
    )
    catalog.create_vocabulary(
        jschon.URI('https://spec.openapis.org/reference/vocab/2020-12/oastype'),
        OasType,
        OasSubType,
    )
    catalog.create_metaschema(
        jschon.URI(
            'https://spec.openapis.org/reference/dialect/2020-12/oastype'
        ),
        jschon.URI("https://json-schema.org/draft/2020-12/vocab/core"),
        jschon.URI("https://json-schema.org/draft/2020-12/vocab/applicator"),
        jschon.URI("https://json-schema.org/draft/2020-12/vocab/unevaluated"),
        jschon.URI("https://json-schema.org/draft/2020-12/vocab/validation"),
        jschon.URI(
            "https://json-schema.org/draft/2020-12/vocab/format-annotation"
        ),
        jschon.URI("https://json-schema.org/draft/2020-12/vocab/meta-data"),
        jschon.URI("https://json-schema.org/draft/2020-12/vocab/content"),
        jschon.URI('https://spec.openapis.org/reference/vocab/2020-12/oastype'),
    )
    return catalog

def init_gremlin(drop_all=True):
    gremlin_conn = GremlinRemoteConnection(
        "ws://localhost:8182/gremlin",
        "g",
    )
    gremlin_g = gremlin_traversal().withRemote(gremlin_conn)
    if drop_all:
        gremlin_g.V().drop().iterate()
    return gremlin_g, gremlin_conn

class Parser:
    def __init__(
        self,
        api_desc_name,
        api_desc_base_uri=DOCUMENT_BASE_URI,
        use_rdf=False,
        use_gremlin=False,
        rdf_format='turtle',
        type_filter=(),
        clear_storage=True,
    ):
        self._api_desc_name = api_desc_name
        self._api_desc = None

        if api_desc_base_uri == DOCUMENT_BASE_URI:
            # We're using the default base URI, so at least customize
            # it with the name we have for this API description.
            self._api_desc_base_uri = rfc3986.uri_reference(api_desc_name) \
                .resolve_with(api_desc_base_uri)
        else:
            self._api_desc_base_uri = api_desc_base_uri

        # We don't use the catalog directly, but its presence
        # lets us know that jschon has been set up properly.
        self._jschon_catalog = None

        # Initialize the stack with the root pointer, which is never popped.
        self._stack = [JSONPointer('')]
        self._seen = {}
        self._refs = {}

        self._oastypes = {}
        self._type_filter = type_filter
        self._filtered = []

        # If we are using a persistant data store, should we clear it?
        self._clear_storage = clear_storage

        self._use_rdf = use_rdf
        self._rdf_g = rdflib.Graph() if use_rdf else None
        self._rdf_nodes = {}

        self._use_gremlin = use_gremlin
        self._gremlin_g = None
        self._gremlin_conn = None
        self._gremlin_nodes = {}

    def __enter__(self):
        if self._use_gremlin:
            self._gremlin_g, self._gremlin_conn = \
                init_gremlin(drop_all=self._clear_storage)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._use_gremlin and self._gremlin_conn:
            self._gremlin_conn.close()

    def parse(self):
        # TODO: Are we likely to re-invoke parse()?  Why?
        #       Is there a reason to not just parse on instantiation?
        #       Would we re-parse into different graphs?
        #       Serialize the parsed graph different ways?
        if not self._api_desc:
            self._api_desc = self._load_api_desc()

        if not self._jschon_catalog:
            self._jschon_catalog = init_jschon()

        schema_output = self._evaluate_api_desc()

        for r in sorted(
            schema_output['annotations'],
            key=lambda a: a['instanceLocation']
        ):
            akl = r['absoluteKeywordLocation']
            if akl.endswith('/oasType'):
                self._handle_oastype(r)

        self._link_references()

    def _load_api_desc(self):
        api_desc_file = os.path.join(DESC_DIR, f'{self._api_desc_name}.yaml')
        try:
            with open(api_desc_file) as desc_fd:
                return yaml.load(desc_fd)

        except FileNotFoundError:
            log.debug(f'File "{api_desc_file}" does not exist')
            log.error(f'API description "{self._api_desc_name}" not found')
            sys.exit(-1)

    def _evaluate_api_desc(self):
        try:
            version = self._api_desc['openapi'][0:3]

            # TODO: Add 3.1 support.  And maybe 2.0?
            if version not in ('3.0',):
                log.error(f'OAS v{version} not supported')
                sys.exit(-1)

            schema_file = os.path.join(
                SCHEMA_DIR, 'oas', f'v{version}', 'schema.yaml'
            )
            with open(schema_file) as schema_fd:
                oas_schema_data = yaml.load(schema_fd)

            init_jschon()
            oas_schema = jschon.JSONSchema(oas_schema_data)
            result = oas_schema.evaluate(jschon.JSON(self._api_desc))

            if not result.valid:
                log.error(f'API description not valid')
                if log.isEnabledFor(logging.DEBUG):
                    # TODO: I don't understand/remember the logging config,
                    #       as log.debug won't work here for some reason.
                    schema_errors = io.StringIO()
                    yaml.dump(result.output('detailed'), schema_errors)
                    log.error('\n' + schema_errors.getvalue())
                sys.exit(-1)

            return result.output('basic')

        except KeyError as ke:
            if ke.args[0] == 'openapi':
                log.error('Malformed API description: missing "openapi" field')
                sys.exit(-1)
            raise

        except FileNotFoundError:
            log.debug(f'File "{schema_file}" does not exist')
            log.error(f'Schema for OAS v{version} not not found')
            sys.exit(-1)

    def _get_parent(self, oad_loc_ptr):
        # Note that > would not work as some pointers
        # are neither prefixes nor suffixes of each other
        oad_loc_different = self._stack[-1] != oad_loc_ptr
        while not (self._stack[-1] <= oad_loc_ptr):
            self._stack.pop()
        if oad_loc_different:
            self._stack.append(oad_loc_ptr)

        return self._stack[-2] if len(self._stack) > 1 else None

    def _filter_data(self, short_type):
        if short_type in self._type_filter:
            entry = (
                f'oasType:\t{a}\nlocation:\n\t'
                f'https://openapis.org/demo#{r["instanceLocation"]}'
            )
            self._filtered.append(entry)

    def _handle_oastype(self, r):
        oastype = rfc3986.uri_reference(r["annotation"])

        short_type = oastype.fragment
        if self._filtered:
            self._filter_data(short_type)

        oad_loc_ptr = JSONPointer(r['instanceLocation'])
        parent_loc_ptr = self._get_parent(oad_loc_ptr)

        self._oastypes[oad_loc_ptr.uri_fragment()] = oastype

        self._graph_type(oastype, oad_loc_ptr)

        if short_type == 'reference-object':
            self._record_reference(oad_loc_ptr)

        # Note that an empty string parent pointer
        # is still a parent but has a false-y value
        if parent_loc_ptr is not None:
            self._handle_parent(oad_loc_ptr, parent_loc_ptr)

    def _graph_type(self, oastype, oad_loc_ptr):
        # oastypes are nodes in RDF, but labels in Gremlin
        if self._use_rdf:
            if oastype not in self._rdf_nodes:
                self._rdf_nodes[oastype] = rdflib.URIRef(oastype.unsplit())

        if oad_loc_ptr not in self._seen:
            oad_loc_uri = self._api_desc_base_uri.copy_with(
                fragment=oad_loc_ptr.uri_fragment()
            )
            # XXX: Is this right?
            self._seen[oad_loc_ptr] = oad_loc_uri

            if self._use_rdf:
                self._rdf_nodes[oad_loc_ptr] = rdflib.URIRef(
                    oad_loc_uri.unsplit()
                )
                self._rdf_g.add((
                    self._rdf_nodes[oad_loc_ptr],
                    RDF.type,
                    self._rdf_nodes[oastype],
                ))

            if self._use_gremlin:
                gremlin_obj = next(
                    self._gremlin_g.addV(oastype.fragment)
                    .property('loc', str(oad_loc_ptr))
                )
                self._gremlin_nodes[oad_loc_ptr] = gremlin_obj

    def _record_reference(self, oad_loc_ptr):
        ref_string = oad_loc_ptr.evaluate(self._api_desc)['$ref']

        # TODO: fragment-only for now
        assert ref_string.startswith('#')

        target_uri = rfc3986.uri_reference(ref_string)
        target_ptr = JSONPointer.parse_uri_fragment(target_uri.fragment)
        self._refs[oad_loc_ptr] = target_ptr

    def _handle_parent(self, oad_loc_ptr, parent_loc_ptr):
        parent_loc_uri = self._seen[parent_loc_ptr]
        parent_type = self._oastypes[parent_loc_uri.fragment]

        delta = '.'.join([p for p in oad_loc_ptr[len(parent_loc_ptr):]])
        if self._use_rdf:
            if delta not in self._rdf_nodes:
                delta_uri = parent_loc_uri.copy_with(
                    fragment=rfc3986.uri_reference(
                        '#' + parent_loc_uri.fragment + f'.{delta}'
                    ).fragment,
                ).unsplit()
                self._rdf_nodes[delta] = rdflib.URIRef(delta_uri)
            self._rdf_g.add((
                self._rdf_nodes[parent_loc_ptr],
                self._rdf_nodes[delta],
                self._rdf_nodes[oad_loc_ptr]
            ))

        if self._use_gremlin:
            next(self._gremlin_g.addE(delta)
                .from_(self._gremlin_nodes[parent_loc_ptr])
                .to(self._gremlin_nodes[oad_loc_ptr])
            )

    def _link_references(self):
        for src, dest in self._refs.items():
            if self._use_rdf:
                self._rdf_g.add((
                    self._rdf_nodes[src],
                    rdflib.URIRef(
                        OAS_30_SPEC_BASE_URI.copy_with(
                            fragment='reference-object.target',
                        ).unsplit()
                    ),
                    self._rdf_nodes[dest],
                ))
            if self._use_gremlin:
                next(
                    self._gremlin_g.addE('$ref.target')
                    .from_(self._gremlin_nodes[src])
                    .to(self._gremlin_nodes[dest])
                )

    def serialize_gremlin(self, include=None, exclude=None, sort_by='location'):
        gremlins = []
        trav = self._gremlin_g.V()
        if include:
            trav = trav.hasLabel(*include)
        if exclude:
            trav = trav.not_(__.hasLabel(*exclude))

        for v in trav:
            location = next(self._gremlin_g.V(v).properties('loc').value())
            otype = ' '.join(v.label.split('-')[:-1]).title()
            if otype == 'Openapi':
                otype = 'OpenAPI'
            l = len(otype)
            tabs = '\t'
            if l < 7:
                tabs = '\t\t'

            gremlins.append((otype, tabs, location))
            # print(f'{v.label}:{tabs}"{location}"')

        sort_by_index = {
            'oastype': 0,
            'location': 2,
        }[sort_by]

        for g in sorted(gremlins, key=lambda x: x[sort_by_index]):
            print(f'{g[0]}:{g[1]}"{g[2]}"')

    def serialize_rdf(self, fmt='turtle'):
        print(self._rdf_g.serialize(format=fmt))

    # TODO: This should probably be called something else
    def serialize_filtered(self):
        print('\n\n'.join(self._filtered))

# Note: currently unused
FILTER = ('openapi-object', 'info-object', 'reference-object')

if __name__ == '__main__':
    argc = len(sys.argv) - 1
    api_desc_name = sys.argv[1] if argc > 0 else 'petstore'
    graph_type = sys.argv[2] if argc > 1 else 'gremlin'
    serialize_only = argc > 2

    with Parser(
        api_desc_name,
        use_gremlin=graph_type == 'gremlin',
        use_rdf=graph_type == 'rdf',
        clear_storage=(not serialize_only)
    ) as parser:
        if not serialize_only:
            parser.parse()

        if graph_type == 'gremlin':
            parser.serialize_gremlin(
                exclude=('schema_object', 'reference_object')
            )
        elif graph_type == 'rdf':
            parser.serialize_rdf()
