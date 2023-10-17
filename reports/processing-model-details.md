# Clarifying the Processing Model(s) for the OpenAPI Specification

This document is a supplement to the [Processing Model for the OpenAPI Specification summary report](processing-model-summary.md).  The summary provides an introduciton, overview, and high-level recommendations.  This detailed docment defines the terminology needed to explain the issues in detail, goes through a series of examples, and provides more detailed recommendations.

A _processing model_ is a set of rules for parsing the documents in an OpenAPI Description (OAD) and performing any additional work required to create a usable in-memory representation.  An example of "additional work" would be resolving `operationId`s in Link Objects to matching `operationId`s in Path Item Objects.

The OASComply validating/linting parser project, which is intended to be the basis for future conformance test suite and / or certification work, can only validate that an OpenAPI Description (OAD) is parsed and processed correctly if there is a well-defined process for doing so.  Or at least a set of well-defined processes among which a user can choose.

## Processing Context

To understand the processing model options, we must first understand the concept of a _processing context_.

The processing context is what tells a parser or other tool what to expect from a piece of data.  There are three types of processing context that are relevant to this discussion:

* **parent context**: This is the context imposed by the structure one JSON object on its child objects; for example the `info` field in an OpenAPI Object expects an Info Object
* **reference context**: This context is imposed on a *reference target* by the reference source, which works as follows:
    * All uses of `$ref`: the context of the object containing the `$ref`
    * `operationRef` in a Link Object: an Operation Object
    * entries under `mapping` in a Discriminator Object: a Schema Object (or a Reference Object in OAS 3.0)
* **entry point context**: This is how parsing begins, and is either provided by a user, or is implied by the `application/openapi+json` or `application/openapi+yaml` media type; it always expects an OpenAPI Object

### Contexts in agreement

The difficulty in processing OpenAPI Descriptions (OADs) occurs when two of the above contexts disagree with each other.  But first, let's look at an example where both contexts agree to illustrate the two context types (I am omitting the Info Object for brevity):

```YAML
openapi: "3.1.0"
components:
  responses:
    foo:
      description: Foo response
  schemas:
    foo:
      description: Foo schema
paths:
  /foo
    get:
      summary: Get the one and only foo!
      responses:
        "200":
          description: Foo singleton representation
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/foo"
```

For the entry point context (at location `#`), we might either pass this whole document to a tool to process, or it might be encountered as an HTTP response with `Content-Type` set to `application/openapi+yaml`.

Here are all of the parent contexts within the document (Recall that in OAS 3.1, the Schema Object directly supports references, and is never replaced by a Reference Object):

| Location | Parent Object | Document Context |
| -------- | ------------- | ---------------- |
| `#/components` | OpenAPI Object | Components Object |
| `#/components/responses/foo` | Components Object | Response or Reference Object |
| `#/components/schemas/foo` | Components Object | Schema Object |
| `#/paths` | OpenAPI Object | Paths Object |
| `#/paths/~1foo` | Paths Object | Path Item Object |
| `#/paths/~1foo/get` | Path Item Object | Operation Object |
| `#/paths/~1foo/get/responses` | Operation Object | Responses Object |
| `#/paths/~1foo/get/responses/200` | Responses Object | Response or Reference Object |
| `#/paths/~1foo/get/responses/200/content/application~1json` | Response Object | Media Type Object |
| `#/paths/~1foo/get/responses/200/content/application~1json/schema` | Media Type Object | Schema Object |

In this example, we only have one reference: `#/paths/~1foo/get/responses/200/content/application~1json/schema/$ref`, which is in a Schema Object and therefore expects a Schema Object as its target at `#/components/schemas/foo`.  As seen in the table above, the parent context of `#/components/schemas/foo` _also_ expects a Schema Object, and the value there is in fact a valid OAS 3.1 Schema Object.

So here, the parent contexts and reference contexts agree, and everything is fine.

### Conflicting contexts

Let's make one change to produce an example of conflicting parent and reference contexts, that are not otherwise an error.

We will change then last line:

```YAML
                $ref: "#/components/schemas/foo"
```

to:

```YAML
                $ref: "#/components/responses/foo"
```

The reference context still expects a Schema Object, and the value at `#/components/responses/foo` _is_ a valid OAS 3.1 Schema Object, as the syntax of Schema Objects and Response Objects overlap.

_Note:  I acknowledge that it's not an interesting Response Object, but since OAS 3.1 Schema Objects ignore unknown keywords, it could be substantially more complex and the example would still behave the same.  But it would be less readable.  Also, this simpler example works for both 3.0 and 3.1_

So now we have a reference target that satisfies its reference context (Schema Object), but that reference context disagrees with its parent context (Response Object).

There is nothing in the specification that outright forbids this.  For now, we are just establishing that it is possible.  We will return to what ought to happen in such a situation later.

### Ambiguous contexts

This has been straightforward so far because it is all in one file, which means that parent contexts are established for the entire OAD.  But consider this arrangement, where both of these files are in the same directory (_Note: File extensions in `$ref` are problematic, but I'm including it to keep the example simple._):

`openapi.yaml`:

```YAML
openapi: "3.1.0"
components:
  schemas:
    foo:
      description: Foo schema
paths:
  /foo
    get:
      summary: Get the one and only foo!
      responses:
        "200":
          description: Foo singleton representation
          content:
            application/json:
              schema:
                $ref: "foo.yaml"
        "default":
          $ref: "foo.yaml"
```

`foo.yaml`:

```YAML
description: Foo response
```

As humans, we can tell that the schema reference was probably supposed to go to `#/components/schemas/foo`, but no tool would be able to figure that out.  There's no reason you couldn't describe a schema for a response payload as "Foo response", and tools don't analyze descriptions for parsing clues anyway (yet... some AI startup will probably try it eventually).

`foo.yaml` _does not have a parent context_.  It is not (as I understand it) a valid `application/openapi+yaml` document, as it does not have an OpenAPI Object at the root.  It can only be parsed according to a reference context.

In this example, it is parsed twice, with two different reference contexts.  Syntactically, it meets the expectations of both contexts, even though they conflict with each other.  And again, there is nothing in a strict reading of the OAS to say that this is an error.  If one were to flag an error or warning, there is nothing to say which context, if any, imposes the "correct" vs "incorrect" expectation.

But it is definitely confusing.  It is not hard to see how further confusion might set in if yet another reference context is applied where the document _does not_ meet the syntax expectations of that 3rd reference context.  Then you have a single document that is correct twice (in two different ways!) and incorrect once.

If the user truly understands reference-context-based processing, this will make sense.  But I am willing to bet that not all users will find it intuitive, particularly given that these processing rules are never explicitly specified and are not strictly required.  We will return to this example later.

### Summary (Processing Context)

This section defined several terms:

* _processing context_: expectations that the parser has for the next chunk of data
* _parent context_: expectations imposed by the data's parent OAS-defined Object
* _reference context_: expectations imposed by a reference to the data
* _entry point context_: expectations imposed by a user initiating parsing, or by a media type or other metadata in an automated parsing scenario

It also gave examples of three scenarios, all of which are allowed by a strict reading of either OAS 3.0 or 3.1 (using 3.1 for the examples):

* agreement between parent and reference contexts
* conflict between parent and reference context
* ambiguity due a document without any parent context, with multiple conflicting reference contexts

### Processing Models

Processing context helps us understand what decisions need to be made on a small scale.  A _processing model_ provides an overall approach to making use of processing contexts to understand an OpenAPI Description.  There are two polar opposite approaches that we will discuss throughout the rest of this report.  Towards the end, we will consider hybrid approaches, but it is simpler to only define these two for now.

Fundamentally, OAS implementations were guided to one processing model by older versions of the specification, while JSON Schema, as incorporated into OAS 3.1, requires the other.  The conflict between them also gives us an opportunity to clarify requirements, including how to handle the ambiguities and contextual conflicts discussed above.

Before we do that, in this document, _"parsing"_ refers to reading the JSON data from the entry document and any references, and ensuring that it is syntactically correct.  _"Processing"_ includes additional steps such as resolving `operationId` correlations between Link Objects and Operation Objects that are not included in basic parsing, and therefore have additional considerations affecting their implementation.

#### Reference-driven processing

This approach is what OpenAPI f.k.a. Swagger 2.0 implies with its statement that:

> The Swagger representation of the API is made of a single file. However, parts of the definitions can be split into separate files, at the discretion of the user.

In this approach, the only data parsed is that indicated by the entry context and any reference context.  The parent context is only used for descendants of structures reached via entry and reference contexts, and is calculated assuming that the reference context of the parent is correct.

This requires processing every reference target as a distinct step, even if the data has been seen by reaching it from another reference (directly or as a descendant of a reference target or the entry point).

Presumably, most major OAS tools use this form of processing based on comments on the OpenAPI Slack and the phrasing in the 2.0 specification.  This approach likely works (with some ambiguities and potentially counter-intuitive behaviors) for OAS 3.0.  There are certain cases where it does **not** work for OAS 3.1.

#### Document-driven processing

This approach is what JSON Schema, on its own, requires:  processing must start from a document root (which can be embedded in a larger document as JSON Schema draft 2020-12 can be embedded in OAS 3.1), and must process the entire document, even if not all of it is used.

Encountering a reference to a new document requires that entire document to be loaded and parsed.  Subsequent references to the contents of that same document may be resolved from the initial parsing.

If a referenced document is never referenced as a whole (using n absolute-URI, or a URI with an empty JSON Pointer fragment), the user _must_ indicate the expected contents of the document.  If only parts of the document contain OpenAPI Description data, then the user must indicate which parts and what sort of data they are expected to contain.  While there are limited scenarios in which the structure of an entire document can be inferred from a reference target within it, this is not generally feasible so we will not examine it in detail.  Such a technique can reduce the scenarios when a user must supply document type info, but never eliminate it.

It is unclear how many, if any, OAS tools use this approach.  However, certain OAS 3.1 descriptions can only be parsed correctly if at least all Schema Objects are processed in this manner.  This will be explored in detail in the "Context-provided information" section.

### Summary (Processing Models)

This section made a distinction between _parsing_ (syntax) and _processing_ (which includes parsing as well as additional steps once all syntax has been parsed).

It then defined two strict processing models that span the possible options, which we will use in discussing further processing behaviors:

* _reference-driven processing_, based on the apparent implications of the OAS f.k.a. Swagger 2.0 specification
* _document-driven processing_, based on the explicitly defined approach of recent JSON Schema drafts

## Context-provided information

In addition to syntax expectations, other information is attached to the context as Objects are parsed.  This information is then used while parsing later Objects.  As there is more distance between where this information is defined and where it is used, the specification's intent is often less than clear.

This section will look at the information that gets attached to the context, and what happens when a parse must make a choice about which context to use.  In both 3.0 and 3.1, this can produce behavior that is arguably counter-intuitive.  In 3.1, it can result in behavior that outright contradicts the normatively cited JSON Schema specification.

### Taxonomy of contextual information

The following bits of information are used in non-local connections between parts of an OAD, and therefore must be read from context:

| OAS Version | Object | Information | Usage Notes |
| ----------- | ------ | ----------- | ----------- |
| 3.x | OpenAPI Object | `openapi`   | Sets the OAS version for the entire OAD |
| 3.1 | OpenAPI Object | `jsonSchemaDialect` | Default JSON Schema dialect when it is not set by `$schema` in a Schema Object |
| 3.x | Info, Contact, and License Objects) | general metadata | not directly used by other Objects, but may be associated with the entire OAD by tools which can have legal implications with information such as licensing |
| 3.x | Components Object | component names | schema names in the Discriminator Object; security scheme names in the Security Requirement Object |
| 3.x | Server Objects | URL prefixes and metadata | Path Item Object and Operation Object |
| 3.x | Tag Objects | tag metadata | Operation Object |
| 3.x | Operation Objects | `operationId` | Link Object |
| 3.1 | Schema Object | `$id` | sets the base URI for all relative URI-references in the schema object and its children without their own `$id`s, which can dramatically change how references resolve, with security implications; also sets the canonical URI for the schema as a reference target — other URIs may not be supported by all tools |
| 3.1 | Schema Object | `$anchor` | creates a plain name URI fragment that can be referenced |
| 3.1 | Schema Object | `$dynamicAnchor` | creates a plain name URI fragment that can be referenced as with `$anchor`-created fragments, but that _also_ have special behavior when referenced using the `$dynamicRef` keyword |
| 3.1 | Schema Object | `$schema` | when present in a document root, or in a subschema alongside `$id`, determines the dialect to use for interpreting the schema and all subschemas unless and until another `$schema` changes the dialect |


### Non-schema contextual information

All of the contextual information other than information from Schema Objects has well-defined, if potentially counter-intuitive, behavior under reference-driven processing.

Every identifier (such as a component name or an `operationId`) or other metadata (such as the `openapi` version or the Info Object) that is parsed is ultimately included in the OAD.  Once parsing is complete, features that depend on this information can unambiguously be resolved from it.

However, there are some confusing outcomes.

The OAS recommends against using `operationId`s from Operation Objects in documents other than the entry document, as they must be unique throughout the OAD and collisions are more likely across multiple documents.  This feels like a design smell, and we will return to it in the "Recommendations" section.

The other difficulty is that reference targets outside of the entry document may have been written with the expectation that they would be resolved within their own documents (using the parent context).  This is particularly true if a reference targets part of another OAD's entry document, which would supply the relevant context.

While document-driven processing would avoid violating this author expectation, it brings in additional complexity as noted by the spec for `operationId`.  While the Components Object, Tag Objects, and the globally applicable Server Objects can only be reached once in reference-driven processing, document-driven processing would introduce additional sources for those objects from any other documents written as OAD entry points, which would increase the likelihood of collisions.

Let's look at some examples:

#### Security Requirement Object example

Here is our entry document, `https://example.com/openapi`:

```YAML
openapi: 3.1.0
components:
  securitySchemes:
    basic:
        type: http
        scheme: basic
    key:
        type: apiKey
        name: X-API-Key
        in: header
paths:
  /x:
    $ref: ./components#/components/pathItems/anItem
```

...and our components document, `https://example.com/openapi/components`

```YAML
openapi: 3.1.0
components:
  securitySchemes:
    key:
      type: apiKey
      name: X-API-Key
      in: query
  pathItems:
    anItem:
      get:
        security:
        - key: []
        - basic: []
```

With reference-driven parsing, the behavior here is well-defined:  both the `basic` and `key` Security Requirement Objects are resolved from the entry document.

With document-driven parsing, the behavior is unclear:  the `basic` requirement can only be satisfied from the entry document, while the `key` requirement could be satisfied from either.

Satisfying it within the same document would seem to align with authorial intent, but that is a difficult thing to divine sometimes (but important enough that we will examine it more later on).  With the components document not being usable as an entry document of its own (there is no `paths` or `webhooks` entry), with reference-driven processing the `#/components/securitySchemes` section is essentially unreachable and unusable.  Which feels odd, but most specifications have corners where semantically useless things are syntactically valid, so that doesn't mean that it's wrong.

If all of our examples felt like this, there would be a fairly compelling argument for simply clarifying reference-driven processing as the requirement.  However, other scenarios are less clear.

#### Discriminator Object example

Here is our entry document, `https://example.com/openapi`:

```YAML
openapi: 3.1.0
components:
  schemas:
    person:
      type: object
      properties:
        pets:
          type: array
          items:
            $ref: ./components#/components/schemas/pet
        coolness:
          type: integer
          minimum: 0
    cat:
      description: "A really cool person"
      $ref: "#/components/schemas/person"
      properties:
        coolness:
          minimum: 10
paths:
  /person/{id}:
    parameters:
    - name: id
      in: path
      schema:
        type: integer
      required: true
    get:
      summary: 'A person'
      responses:
        "200":
          description: 'OK'
          content:
            application/json:
              $ref: #/components/schemas
```

...and also a components document, `https://example.com/openapi/components`:

```YAML
openapi: 3.1.0
components:
  schemas:
    pet:
      $dynamicAnchor: collectionItem
      type: object
      required: [species]
      properties:
        species:
          type: string
          enum: [dog, cat]
      discriminator:
        propertyName: species
    dog:
      allOf:
      - $ref: "#/components/schemas/pet"
      properties:
        species:
          const: dog
    cat:
      allOf:
      - $ref: "#/components/schemas/pet"
      properties:
        species:
          const: cat
```

I really have no idea what ought to happen in this example.

Reference-driven processing would _only_ process `#/components/schemas/pets` in the components document, once the reference was encountered in the entry document.  Since this example uses the `"allOf"` form of the Discriminator Object (as shown in [an example in the OAS itself](https://spec.openapis.org/oas/v3.1.0#fixed-fields-20)), there is nothing that would cause `#/components/schemas/cat` and `#/components/schemas/dog` to be processed at all!  Plus, the Components Object itself, including the component names, would never be processed even if we used the `"oneOf"` or `"anyOf"` form.

As this stands, with reference-driven processing, I would expect a `species` value of `cat` to resolve to `https://example.com/openapi#/components/schemas/cat`, which of course is the wrong schema entirely!  I would expect a value of `dog` to fail to resolve.

You can argue that this is simply user error, and if strict reference-driven processing were explicitly documented as a requirement, that error would be clear.  There is also a simple work-around that can be done by using the Discriminator Object's `mapping` field with URI-references to avoid having to resolve an implicit component name.  Those references would also cause the relevant schemas to be parsed.

But you can also argue that there is an obvious authorial intent here which would only be solved by both using document-driven processing, _and_ determining that the most local Components Object is the one used for resolving the discriminator value.  This gets into the question of user expectations, and what level of responsibility the OAI has in setting and meeting those expectations.  We will examine this topic in detail in its own section later on.

### Schema-based contextual information

JSON Schema uses both document-related contextual information _and_ contextual information from what it calls the "evaluation path", which tracks reference context.  There are several ways in which strict reference-driven processing breaks JSON Schema in OAS 3.1.

While some of these schema authoring techniques are advanced and occupy rather niche spaces in schema design, those niches are important, and in many cases have been advertised by the OpenAPI Initiative as features of 3.1.

#### Relative URI-reference resolution

Used in:

* OAI blog post [JSON Schema bundling finally formalized](https://www.openapis.org/blog/2021/08/23/json-schema-bundling-finally-formalised)

Consider two schema files:

`https://example.com/some-schema`:

```YAML
$id: https://example.com/some-schema
$defs:
  outer:
    $id: https://other.org/outer
    $defs:
      inner:
        $ref: foo
```

`https://other.org/foo`:

```YAML
$id: https://other.org/foo
type: string
```

Assume that we have a Schema Object in an OAS 3.1 document that includes `"$ref": "https:/example.com/some-schema#/$defs/outer/$defs/inner"`.  If we use document-driven parsing, then we'll notice both `$id`s, and particularly `#/$defs/outer/$id` which sets the base URI for `#/$defs/outer` and its subschemas, including `#/$defs/outer/$defs/inner`.  If we use reference-driven parsing, we will ignore everything except `#/$defs/outer/$defs/inner`, which means we will ignore all of the `$id`s.

When we hit `$ref: foo`, how it resolves depends on what kind of processing we used to reach it:

* **document-driven:** resolves to `https://other.org/foo`, which is a schema imposing `type: string`
* **reference-driven:** resolves to `https://example.com/foo`, which may or may not exist

Note that if something that at least _looks_ like a JSON Schema exists at `https://example.com/foo`, reference-driven parsing will silently and incorrectly attempt to apply it.  This will likely lead to the wrong behavior, and may have security implications.

#### `$id` detection as a reference target

Note that our OAS 3.1 Schema Object could have referenced `https://other.org/outer`, which would have produced the right `foo` reference resolution either way.  However, assuming this schema is _not_ deployed at `https://other.org/outer`, any OAS tool will need to be told to parse and process the document `https://example.com/some-schema` to find it.

This could be done by pre-loading the `https://example.com/some-schema` document unconditionally, or by configuring the tool to know that that document should be loaded if `https://other.org/outer` is encountered, _instead_ of trying to load `https://other.org/outer` directly.

#### Plain-name fragment detection

Plain-name URI fragments, created by the `$anchor` keyword, allow you to separate the identifier of a schema from its location within a document.  Similar to referencing `$id`, a fragment created by `$anchor` can only be used if the document that contains it has been processed.  However, since this only concerns the fragment, the absolute-URI portion of the URI will already map to the correct document, making this one of the easier schema context cases.

#### Dynamic references and anchors

Used in:

* JSON Schema blog post [Using Dynamic References to Support Generic Types](https://json-schema.org/blog/posts/dynamicref-and-generics)

The `$dynamicAnchor` keyword _also_ creates a plain-name fragment, which can be used in the same way as those created by `$anchor` (there is only one namespace for URI fragments).  However, JSON Schema implementations note which fragments are created by the `$dynamicAnchor` keyword, and use them in an unusual way when referenced by `$dynamicRef`.

Evaluating `$dyanmicRef` looks for `$dynamicAnchor`-created fragments in each _whole document_ that has been encountered along the evaluation path.  This is _very_ different from the OAS's use of reference context, where only the portions of documents that are reference targets are processed.

Given these schemas:

```YAML
$id: https://example.com/schemas/lib
$defs:
  foo:
    $dynamicAnchor: dynFoo
  bar:
    $ref: bar
```

```YAML
$id: https://example.com/schemas/bar
$dynamicRef: "#dynFoo"
$defs:
  barFoo:
    $dynamicAnchor: dynFoo
```

Let's assume that these are referenced from an OAS 3.1 entry document that _does not_ use `$dynamicAnchor` anywhere, just to keep this example manageable.

A Schema Object that uses `$ref: https://example.com/schemas/bar` will hit the `$dynamicRef: "#dynFoo"` immediately, and it will correctly resolve to `https://example.com/schemas/bar#dynFoo`, which is located at `https://example.com/schemas/bar#/$defs/barFoo`, as that is the only document in the evaluation path that has the correct `$dynamicAnchor`.

But a Schema Object that uses `$ref: https://example.com/schemas/lib#/$defs/bar` will behave differently depending on whether document-driven or reference-driven processing is used.

With document-driven processing, the whole `https://example.com/schemas/lib` document will be processed, and the `$dynamicAnchor: dynFoo` located at `https://example.com/schemas/lib#/$defs/foo` will be noticed.  After passing through the `$ref: bar` and hitting the `$dynamicRef: "#dynFoo"`, the `$dynamicAnchor` in the `https://example.com/schemas/lib` document will be correctly found as the `$dynamicAnchor: dynFoo` in the earliest-seen document along the evaluation path.

However, with reference-driven processing, only the portion of the document at `$ref: https://example.com/schemas/lib#/$defs/bar` will be read, ignoring the schema at `#/$defs/foo` that contains the `$dynamicAnchor: dynFoo`.  Therefore with reference-driven processing, the `$dynamicRef` will _incorrectly_ resolve to the anchor within `https://eample.com/schemas/bar`.

#### Dialect switching with `$schema`

Used in:

* OAI blog post [JSON Schema bundling finally formalized](https://www.openapis.org/blog/2021/08/23/json-schema-bundling-finally-formalised)

Let's assume someone has defined a "date range" vocabulary with the validation assertion keywords `minDate` and `maxDate`, both of which take dates in the format `YYYY-MM-DD` and apply to string values that use the same date format.  Let's also assume that someone has created a dialect meta-schema `https://example.com/dialects/2020-12-with-date-range` that consists of the standard 2020-12 dialect plus this date-range vocabulary, and with the `format-assertion` vocabulary replacing the `format-annotation` one.  And finally, let's assume that they have provided the necessary plugins for all JSON Schema-related tools to handle those keywords and support `format` as an assertion properly.

Given the following schema document:

```YAML
$id: https://example.com/schemalib/19xx-decades
$schema: https://example.com/dialects/2020-12-with-date-range
$defs:
  nineties:
    type: string
    format: date
    minDate: 1990-01-01
    maxDate: 1999-12-31
  eighties:
    type: string
    format: date
    minDate: 1980-01-01
    maxDate: 1989-12-31
  # etc
```

If an OAS 3.1 Schema Object does a `$ref: https://example.com/schemalib/19xx-decades#/$defs/nineties`, that Schema Object should accept the instance `1990-01-01`, but should fail validation for `2000-01-01` (because it is out of range) or `whatever` (because it is not a date).

However, if OAS tooling uses reference-driven processing and extracts only the schema object at `https://example.com/schemalib/19xx-decades#/$defs/nineties` and hands it to the JSON Schema validator in isolation, it will not see the `$schema` value, will not load the correct vocabularies, and will accept `2000-01-01` as it will just ignore the unrecognized `minDate` and `maxDate` keywords.  And depending on its configuration, it will most likely accept `whatever` as it will expect `format` validation to be done externally by reading annotations.

Only if this is done with document-driven processing will the complete document correctly be handed to the JSON Schema validator, which will load the extensions needed to support the custom validation assertions.

#### Default dialect selection

Consider this OAS component document:

`https://example.com/components`:

```YAML
openapi: 3.1.0
jsonSchemaDialect: https://example.com/dialects/2020-12-with-date-range
components:
  schemas:
    nineties:
      type: string
      format: date
      minDate: 1990-01-01
      maxDate: 1999-12-31
```

And this OAS entry document:

`https://example.com/openapi`:

```YAML
openapi: 3.1.0
paths:
  /foo:
    get:
      summary: Get the one and only foo!
      responses:
        "200":
          description: Foo singleton representation
          content:
            application/json:
              schema:
                type: object
                properties:
                  whenInTheNineties:
                    $ref: "components#/components/schemas/nineties"
```

Note that the entry point does not set `jsonSchemaDialect`, and is therefore using the default OAS 3.1 dialect.  But the components document uses our custom date range document.

This example is a little different from the others as it involves the interaction between the OpenAPI Specification and JSON Schema.  The correct behavior depends on how one reads the definition of `jsonSchemaDialect` and squares it with reasonable expectations of OpenAPI Description authors.  Here is the definition from OAS 3.1.0:

> The default value for the `$schema` keyword within Schema Objects contained within this OAS document. This MUST be in the form of a URI.

And now we experience the pain resulting from the OAI's decision to (until just recently in late 2023) refer to the logical, post-processing entity as an ["OpenAPI Document"](https://spec.openapis.org/oas/v3.1.0#openapi-document).  Here we have the not-quite-identical phrase "OAS document" with a little "d", and we have to decide whether that little-d "document" means "document" in the normal sense, or whether "OAS document" is supposed to mean "OpenAPI Document", in which case "document" doesn't mean "document" but "logical structure built by processing the entry document and all of the things it references."

Fortunately, the TSC has agreed to use "OpenAPI Description" for the logical entity in future updates to the specification, which will be an opportunity to clarify this sort of thing.

For now, I'll observe that when I was involved in adding the `jsonSchemaDialect` keyword to OAS 3.1, I assumed that "document" meant "document" in the normal, intuitive sense.  Certainly the fictional author of the `https://example.com/components` example above thought it meant "normal document", or else there would be no reason to include `jsonSchemaDialect` at all.  A components document like this cannot serve as an entry document, so if only reference-driven processing is allowed, the `jsonSchemaDialect` keywords would never take effect.

Further, I will argue that it would not be reasonable to allow entry documents that share a components document of this sort to re-define the default schema dialect in ways that the author of the components document could never have anticipated.  Using reference-driven processing to bypass the clear `jsonSchemaDialect` choice and impose an unrelated one would be surprising.  Requiring a referring entry document to _match_ the `jsonSchemaDialect` value in order to preserve the schema behavior would be impractical (different components documents might require different values) and fragile even in the cases where it might (at least temporarily) work.

It seems clear to me that one approach (document-driven processing) ensures the referenced schema author's intent is respected, while the other (reference-driven processing) incorrectly disregards it.  But this does depend on my interpretation of the spec, which will be the topic of our next major section: User expectations.

But first, there is one more type of contextual information to consider!

### Context and OAS versions

OAS 3.0 and 3.1 are almost, but not quite, compatible.  Consider the following Reference Object:

```JSON
{
  "$ref": "somewhere",
  "summary": "summarized summary"
}
```

In OAS 3.0, `summary` is ignored.  In OAS 3.1, the `summary` is added to a copy of the reference target if that Object type allows a `summary` field, overwriting the original field if it was present.  If `summary` is not allowed, it is ignored.

If an OAS 3.0 entry document references into an OAS 3.1 components document that includes a Reference Object like the above one, reference-driven parsing means that `summary` would be ignored, contrary to the expectations of the author of that reference object.

A more ambiguous case happens if the entry document references a document that contains only bits of OAS data, and no root-level OpenAPI Object that sets the version with an `openapi` field.  There is no document context in this approach, but the reference context may or may not match the intent of the author.  Given that OAS 3.1 allows documents that just have `components` without `paths` or `webhooks`, and OAS 3.1 has a slot under the Components Object for all referenceable types (unlike 3.0 which does not support `pathItems`), it would seem preferable to avoid such fragmentary, non-versioned documents in OADs involving 3.1.

### Summary (Context-provided information)

This section explained how conflicting contexts have implications beyond the syntax expectations imposed on reference targets.  It also examined how both reference-driven processing and document-driven processing handle certain scenarios well, and others in ways that are either confusing or outright incorrect according to specification requirements.

We broke contextual information down into a few categories:

* non-Schema Object information, which behaves in a well-defined although not always intuitive manner under reference-driven processing, and would require disambiguation and possibly changed behavior with document-driven processing
* Schema Object information, which normatively _requires_ document-driven processing (sometimes supplemented by the evaluation path, which is similar to reference context), which is not entirely obvious from OAS 3.1 given the historical approach of reference-driven processing
* OAS version information, which can result in arguably incorrect behavior if versions are crossed, which can happen more easily with fragmentary documents that lack an OpenAPI Object and `openapi` field to set their own version

## Context and User Expectations

When authoring an OAS document (whether an entry document, reference document, or a document that can be used in either manner), most people are thinking in terms of _parent context_.  They will expect the document to function accordingly when it is used.

Later, when linking multiple documents into one or more OpenAPI Descriptions using references, a knowledgeable user will ensure that the reference contexts they impose match the parent contexts present in the documents.  If this were always the case, we would not have any problems.

However, there are several ways that this state of agreeable contexts can diverge:

1.  Not all users are sufficiently knowledgeable
1.  All users make mistakes from time to time
1.  Published documents sometimes change

Users will often want tools to catch their errors, or notice when a change in a system makes it inconsistent.  While these expectations are not always reasonable, they should be factored in when deciding what the ideal behavior ought to be.

When clarifying the specification, it is good to be precise about what implementations are expected to detect in terms of errors, vs what users cannot reasonably expect a tool to do for them.  Correct alternatives to likely errors should be presented, if not in the specification, then in the learn.openapis.org site.

### User expectations in a large API ecosystem

When Swagger was first created, each API tended to be provided in isolation.  However, it is increasingly common for APIs to function as part of a larger ecosystem.  This requires stronger interoperability guarantees from the OAS as different providers might use differing toolsets when authoring their OpenAPI Descriptions.  Due to the processing model ambiguities discussed here, OADs written for different tools might have different expectations of behavior.  This provides a challenge for efforts like the Workflows spec, which needs to coordinate across OADs from different providers.

Additionally, as seen with the recent creation of a "#sig-industry-standards" channel on Slack, it is also becoming more common for standards groups to publish OAD components for use by any API that works with the relevant sort of data.  This leads to more OADs that might incorporate 3rd-party components by reference.

Finally, a [recent discussion on the OAI Slack](https://open-api.slack.com/archives/C1137F8HF/p1696441821100469) brought up the emerging need for OpenAPI component (including but not limited to schemas) package management.  

All of these trends suggest a world in which OADs are increasingly not only split across multiple documents, but in which those documents come from multiple providers.  In such an environment, treating an OAD as if it were a unified thing under the control of a single publisher is not feasible.  The specification needs to support the referencing needs of this ecological perspective on HTTP APIs.

## Recommendations

The [summary version](reports/processing-model-summary.md) of this report suggests clarifying the reference-driven processing model of OAS 3.0, assuming that most tooling indeed implements such a processing model.  It also suggests defining a document-driven processing model for OAS 3.1, but acknowledges that the state of the tooling landscape may require a hybrid approach.  This section details some ideas that could be involved in such clarifications.

### Clarifying reference-driven processing

Assuming the OAI endorses reference-driven processing as the OAS 3.0 processing model, or at least as an acceptable one for tools to advertise that they support, certain things should be clarified for both tools and OAD authors.

* Are there any scenarios in which a tool MUST, SHOULD, or even MAY check for conflicts between reference context and parent context, if the parent context is known, and how should conflicts be handled?
* Similarly, should multiple conflicting reference contexts be detected and acted upon?
* Users should be advised (whether in the spec or the learn site) against expecting things like Component names of `operationId`s to be resolved from the same document if that document is not the entry document; this is sort-of addressed for `operationId`, but it could be much more clear
* Scenaoris where parsing a non-entry-document encounters fields like `operationId` that _could_ be used to resolve non-reference linkages need clarification.  It seems like always ignoring them would be the most consistent behavior
* The `"allOf"` usage pattern of the Discriminator Object can result in some of the schemas in the class hierarchy never being referenced; users should be warned about this, or additional expectations on parsing should be imposed

### Defining document-driven processing

If full document-driven processing is to be defined for any OAS version, conflicts among Component names, Tag names, `operationId` from different documents need to be addressed.

* Resolving from the local document is almost certainly the most likely to match authorial intent, as noted in the "User Expectations" section
* Are there ever times when such names and identifiers should be resolved from non-local documents, or should such connections be limited to same-document usage?
* If these things can be resolved from different documents, what, if any, behavior is defined in the face of conflicts?  Is there a precedence, or is it an error, or is it implementation-defined?

Document-driven processing is substantially simplified if all documents MUST be proper OpenAPI documents (with an OpenAPI Object at the root) or JSON Schemas.  If documents consisting of some other Object, or consisting of several Objects embedded in generic JSON or YAML are supported, certain things need to be addressed:

* Expectations should be set about how MAY, SHOULD, or MUST support loading such documents
* It should be clarified whether an entry point document MUST be a document, or can be an OpenAPI Object embeded in some other file
* Embedding an OpenAPI Object has two potential cases: arbitrary file structures, and formal embedding in another format, just as JSON Schema is embedded within the OAS

### Hybrid processing for OAS 3.1

If full document-driving processing for OAS 3.1 is too disruptive to the tooling ecosystem, a plausible approach (which was mostly implemented for OASComply's demo milestone in May 2023) would be to require document-style parsing for all Schema Objects, but reference-driven processing for everything else.

The behavior of `jsonSchemaDialect` would need addressing, and the correct approach there is not immediately clear.  But other than that, the Schema Object processing rules are already well-defined by JSON Schema, as long as schemas can either be automatically detected, or users indicate what documents, or parts of documents are schemas.  The specification should make it clear that failure to process Schema Objects in this way will produce non-compliant results.

### Moonwalking to success

Moonwalk, as currently proposed, imports whole documents in one, and only one, part of the format.  The names from the documents are namespaced, with the details TBD.  Combined with document-oriented processing for Schema Objects, which would be the only Objects to still use any form of traditional referencing, Moonwalk already has a more clear and consistent processing model than OAS 3.x.
