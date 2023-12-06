# OASComply Processing Model Assessment Suite

This directory contains a set of test cases that can be used to assess
the behavior of an implementation for various referencing cases that
are arguably not clearly defined in the OpenAPI Specification (OAS).

The suite is divided into several functional groups, each of which
gets a directory.  Each group contains a README explainig how to
understand its test cases, and a set of directories, each of which
contains one test case.

Each case has an `in` directory, containing a multi-document OpenAPI
Description (OAD), one output directory for each relevant processing model
(as defined below) showing whether and how the references and related
behaviors are resolved under that processing model.  The exact contents
of the output directories, including whether and how the processing
model impacts the outcomes, are explained by each group's README.

## Processing models

OAS implementations have to choose how to handle various situations that are
not explicitly covered by the OAS with formatl (MUST, SHOULD, etc.)
requirements.  Providing cases for every possible combination of relevant
decisions is not feasible, so three approaches to processing were chosen
based on how people who have implemented the OAS explained their approaches
in conversations on the OpenAPI Slack.

This suite **does not** offer any opinion as to which processing model
is better or worse under any particular metric.  The goal is to help determine
what processing models have been implemented, which can guide future
improvements to the clarity and interoperability of the OAS.

### Common assumptions

All OAS implementations are assumed to parse and process the entry document
in full.  Processing models differ in how they handle references involving
additional documents.

All processing models assume two logically distinct resolution passes that
take place in the following order:

1. _Primary resolution_ handles `$ref` and `operationRef` (which we will
   call _primary references_), which determine the set of documents and/or
   objects that are part of the OAD
1. _Secondary resolution_ looks up names and identifiers within the set
   of documents and/or objects determined by the primary resolution pass

Without this ordering, secondary resultion can become non-deterministic
when it relies on a particular external reference having already been resolved.

### Single-document processing (a.k.a. Swagger-like processing)

Output directory: `single`

Swagger/OAS 2.0 states that the OAD is logically a single document, regardless
of the use of references.  It is assumed that older tools likely carried this
approach forward to OAS 3.x.

This suite interprets this approach as follows:

* Only the specific primary reference target becomes part of the OAD; the
  other contents of the containing document are completely ignored and need
  not conform to the OAS
* The only way to include an Object under the OAD's Components Object is to
  `$ref` it from the entry document's Components Object

### Multi-document processing (a.k.a. JSON Schema-like processing)

Output directory: `multi`

Some OAS tools have been written by developers who came from the JSON Schema
world.  These follow the JSON Schema pattern in which complete documents
must be parsed before any reference targets can be resolved from them, as
keywords in parent schemas can impact the behaviors of child schemas.

Applying this processing model to OADs has the following implications:

* The tool maintains an awareness of the origin document of each object
* Secondary resolution happens within a single document, rather than a
  logical aggregate "document" rooted at the entry document

### Mixing models

A given tool might mix these processing models.  For example, OAS 3.1 Schema
Objects can only be handled properly with multi-document processing.  However,
it probably makes much more sense to use single-document processing for
Server Objects.

This sort of apparent contradiction is why this assessment suite is needed.
Presumably, tool developers have found solutions that work for their users,
but whether those solutions align with either of these processing models,
or involve some other approach, is not well-understood.

### Variations

There are many possible variations on these two models.  For example,
using reference-driven processing as is done with the single-document
approach, but recognizing references of the form `#/components/<type>/<name>`
as named components that are usable for secondary resolution.

This sort of type-assignment-by-JSON Pointer is not described in the OAS,
and if documents are not, in general, well-formed OAS documents, it could
turn out that such a JSON Pointer does not actually point into a Components
Object despite the apparent structure.  But if documents are generally
well-formed, it allows building up a larger aggregate Components Object
than strict single-document processing does.

This assessment suite does not try to show all possible variations, as
they are purely speculative.  However, we know that at least some tools
implement each of the two that we cover here.

If your tool implements a variation that we should cover, please
[file an issue](https://github.com/OAI/oascomply/issues/new) in the oascomply
repository.
