import sys, json, yaml, os.path
from pprint import pprint

import rfc3986
from rfc3986.builder import URIBuilder
from jschon import create_catalog, JSON, JSONSchema, URI
from jschon.catalog import Source
from jschon.jsonpointer import JSONPointer
import rdflib
from rdflib.namespace import RDF

from gremlin_python.process.anonymous_traversal import traversal
from gremlin_python.driver.aiohttp.transport import AiohttpTransport
from gremlin_python.driver.driver_remote_connection import \
    DriverRemoteConnection

from oastype4jschon import OasType, OasSubType

# Note that you need 3.0.3 in the URI to get it to resolve.
# The analogous URI with just 3.0 does not redirect.
OAS_30_SPEC_BASE_URI = \
    rfc3986.uri_reference('https://spec.openapis.org/oas/v3.0.3')

# This is totaly arbitrary.
DOCUMENT_BASE_URI = rfc3986.uri_reference('https://example.com/oad')

LOCAL_DIR = os.path.dirname(os.path.abspath(__file__))

OASTYPE_METASCHEMA = json.load(open(
    os.path.join(LOCAL_DIR, '..', 'schemas', 'meta', 'oastype.json')
))
OASTYPE_DIALECT = json.load(open(
    os.path.join(LOCAL_DIR, '..', 'schemas', 'dialect', 'oastype.json')
))

OAS_30_SCHEMA = yaml.safe_load(open(
    os.path.join(LOCAL_DIR, '..', 'schemas', 'oas', 'v3.0', 'schema.yaml')
))

OAS_DOC = yaml.safe_load(open(
    os.path.join(LOCAL_DIR, '..', 'descriptions', 'petstore.yaml')
    # os.path.join(LOCAL_DIR, '..', 'descriptions', 'api.github.com.yaml')
    # os.path.join(LOCAL_DIR, '..', 'descriptions', 'cloudflare.yaml')
))

class InMemorySource(Source):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._registry = {}

    def register(self, relative_path, schema):
        self._registry[relative_path] = schema

    def __call__(self, relative_path):
        return self._registry[relative_path]

gremlin_conn = DriverRemoteConnection(
    "ws://localhost:8182/gremlin",
    "g",
    # transport_factory=lambda: AiohttpTransport(
    #     call_from_event_loop=True
    # )
)
gremlin_g = traversal().withRemote(gremlin_conn)
gremlin_g.V().drop().iterate()


catalog = create_catalog('2020-12')

in_memory_source = InMemorySource()
in_memory_source.register('meta/2020-12/oastype', OASTYPE_METASCHEMA)
in_memory_source.register('dialect/2020-12/oastype', OASTYPE_DIALECT)
catalog.add_uri_source(
    URI('https://spec.openapis.org/reference/'),
    in_memory_source,
)
catalog.create_vocabulary(
    URI('https://spec.openapis.org/reference/vocab/2020-12/oastype'),
    OasType,
    OasSubType,
)
catalog.create_metaschema(
    URI('https://spec.openapis.org/reference/dialect/2020-12/oastype'),
    URI("https://json-schema.org/draft/2020-12/vocab/core"),
    URI("https://json-schema.org/draft/2020-12/vocab/applicator"),
    URI("https://json-schema.org/draft/2020-12/vocab/unevaluated"),
    URI("https://json-schema.org/draft/2020-12/vocab/validation"),
    URI(
        "https://json-schema.org/draft/2020-12/" +
        "vocab/format-annotation"
    ),
    URI("https://json-schema.org/draft/2020-12/vocab/meta-data"),
    URI("https://json-schema.org/draft/2020-12/vocab/content"),
    URI('https://spec.openapis.org/reference/vocab/2020-12/oastype'),
)

oas303_schema = JSONSchema(OAS_30_SCHEMA)
result = oas303_schema.evaluate(JSON(OAS_DOC))

# Initialize the stack with the root pointer, which is never popped.
stack = [JSONPointer('')]
oas_objects = {}
nodes = {}
rdf_g = rdflib.Graph()
gremlin_nodes = {}
refs = {}

ann = []
for r in sorted(
    result.output('basic')['annotations'],
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
        ref_string = il.evaluate(OAS_DOC)['$ref']
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
gremlin_conn.close()
