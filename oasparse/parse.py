import json, yaml, sys, os.path, logging

import rfc3986

import jschon, jschon.catalog
from jschon.jsonpointer import JSONPointer

import rdflib
from rdflib.namespace import RDF

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
DOCUMENT_BASE_URI = rfc3986.uri_reference('https://example.com/oad')

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

def init_gremlin(drop_all=True):
    gremlin_conn = GremlinRemoteConnection(
        "ws://localhost:8182/gremlin",
        "g",
    )
    gremlin_g = gremlin_traversal().withRemote(gremlin_conn)
    if drop_all:
        gremlin_g.V().drop().iterate()
    return gremlin_g

def get_api_desc(api_desc_name):
    api_desc_file = os.path.join(DESC_DIR, f'{api_desc_name}.yaml')
    try:
        with open(api_desc_file) as desc_fd:
            return yaml.safe_load(desc_fd)

    except FileNotFoundError:
        log.debug(f'File "{api_desc_file}" does not exist')
        log.error(f'API description "{api_desc_name}" not found')
        sys.exit(-1)

def evaluate_api_desc(api_desc):
    try:
        version = api_desc['openapi'][0:3]

        # TODO: Add 3.1 support.  And maybe 2.0?
        if version not in ('3.0',):
            log.error(f'OAS v{version} not supported')
            sys.exit(-1)

        schema_file = os.path.join(
            SCHEMA_DIR, 'oas', f'v{version}', 'schema.yaml'
        )
        with open(schema_file) as schema_fd:
            oas_schema_data = yaml.safe_load(schema_fd)

        init_jschon()
        oas_schema = jschon.JSONSchema(oas_schema_data)
        result = oas_schema.evaluate(jschon.JSON(api_desc))

        if not result.valid:
            log.error(f'API description not valid')
            if log.isEnabledFor(logging.DEBUG):
                # TODO: I don't understand/remember the logging config,
                #       as log.debug won't work here for some reason.
                schema_errors = yaml.dump(result.output('detailed'))
                log.error('\n' + schema_errors)
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

api_desc = get_api_desc('petstore')
schema_output = evaluate_api_desc(api_desc)

# Initialize the stack with the root pointer, which is never popped.
stack = [JSONPointer('')]
oas_objects = {}
nodes = {}
rdf_g = rdflib.Graph()
gremlin_g = init_gremlin()
gremlin_nodes = {}
refs = {}

ann = []
for r in sorted(
    schema_output['annotations'],
    key=lambda a: a['instanceLocation']
):
    akl = r['absoluteKeywordLocation']
    if not akl.endswith('/oasType'):
        continue
    a = r["annotation"]
    base, frag =  a.split('#')
    if frag in ('openapi-object', 'info-object', 'reference-object'):
        entry = f'oasType:\t{a}\nlocation:\n\thttps://openapis.org/demo#{r["instanceLocation"]}'
        ann.append(entry)

    il = JSONPointer(r['instanceLocation'])
    # Note that > would not work as some pointers
    # are neither prefixes nor suffixes of each other
    il_different = stack[-1] != il
    while not (stack[-1] <= il):
        stack.pop()
    if il_different:
        stack.append(il)

    parent = stack[-2] if len(stack) > 1 else None

    oas_type = r['annotation']
    oas_type_uriref = rfc3986.uri_reference(oas_type)
    oas_objects[il.uri_fragment()] = oas_type
    # sys.stderr.write(f'OBJ: {il}\nTYPE: {oas_type}\n\n')
    if oas_type not in nodes:
        nodes[oas_type] = rdflib.URIRef(oas_type)
    if il not in nodes:
        il_uri = DOCUMENT_BASE_URI.copy_with(
            fragment=il.uri_fragment()
        ).unsplit()
        nodes[il] = rdflib.URIRef(il_uri)
    rdf_g.add((nodes[il], RDF.type, nodes[oas_type]))
    gremlin_obj = next(gremlin_g.addV(oas_type_uriref.fragment)
        .property('loc', str(il))
    )
    gremlin_nodes[il] = gremlin_obj

    if frag == 'reference-object':
        ref_string = il.evaluate(api_desc)['$ref']
        assert ref_string.startswith('#') # for now
        target_uri = rfc3986.uri_reference(ref_string)
        target_ptr = JSONPointer.parse_uri_fragment(target_uri.fragment)
        refs[il] = target_ptr

    # Note that an empty string parent pointer is still a parent
    if parent is not None:
        parent_type = oas_objects[nodes[parent].fragment]
        # sys.stderr.write(f'PARENT: "{parent_type}"\n')
        # delta = [JSONPointer.unescape(p) for p in il[len(parent):]]
        delta = '.'.join([p for p in il[len(parent):]])
        if delta not in nodes:
            # print(f'PARENT: "{parent_type}"')
            # parent_uri = rfc3986.uri_reference('about:blank#foo') # str(parent_type))
            parent_uri = rfc3986.uri_reference(str(parent_type))
            # print(f'PARENT URI: "{parent_uri.unsplit()}"')
            # print('DELTA: ' + str(delta_uri))
            delta_uri = parent_uri.copy_with(
                fragment=rfc3986.uri_reference(
                    '#' + parent_uri.fragment + f'.{delta}'
                ).fragment,
            ).unsplit()
            nodes[delta] = rdflib.URIRef(delta_uri)
            # sys.stderr.write(f'DELTA URI: "{nodes[delta]}"\n')
        # sys.stderr.write(f'ADDING:\n\t"{nodes[parent]}"\n\t"{nodes[delta]}"\n\t"{nodes[il]}"\n\n')
        rdf_g.add((nodes[parent], nodes[delta], nodes[il]))
        next(gremlin_g.addE(delta)
            .from_(gremlin_nodes[parent])
            .to(gremlin_obj)
        )

target_frag = 'reference-object.target'
for src, dest in refs.items():
    rdf_g.add((
        nodes[src],
        rdflib.URIRef(OAS_30_SPEC_BASE_URI.copy_with(fragment=target_frag).unsplit()),
        nodes[dest],
    ))
    e = next(
        gremlin_g.addE('$ref.target')
        .from_(gremlin_nodes[src])
        .to(gremlin_nodes[dest])
    )

gremlins = []
for v in gremlin_g.V():#.properties('loc'):
    location = next(gremlin_g.V(v).properties().value())
    otype = ' '.join(v.label.split('-')[:-1]).title()
    if otype == 'Openapi':
        otype = 'OpenAPI'
    l = len(otype)
    tabs = '\t'
    if l < 7:
        tabs = '\t\t'
    # gremlins.append((v.label, tabs, location))
    gremlins.append((otype, tabs, location))
    # print(f'{v.label}:{tabs}"{location}"')

for g in sorted(gremlins, key=lambda x: x[2]):
    pass
    # print(f'{g[0]}:{g[1]}"{g[2]}"')

# TODO: Does not seem to be a problem not to close in this case, but
#       it definitely is in some others.  Needs investigation.
# gremlin_conn.close()
