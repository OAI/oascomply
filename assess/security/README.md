# Security Scheme and Requirement Cases

The Security Requirement Object performs a type of secondary resolution,
correlating property names with the names of Security Scheme Objects in
a Components Object.

The `in` directory for each case includes a multi-document OpenAPI Description.
The entry document is always named `openapi.yaml`

The `single` and `multi` output directory, corresponding to the two processing
models documented in the [assessment suite's README](../README.md), each
contain a `resolved.yaml` document that conforms to the following JSON Schema:

```YAML
$schema: https://json-schema.org/draft/2020-12/schema

type: object
required: [in]

propertyNames:
    enum:
      - input  # Locations in the input files
      - output # Locations in the output file(s), if relevant

additionalProperties:

    propertyNames:
        $comment: The location of the Security Requirement
        type: string
        format: uri-reference

    additionalProperties:
        $comment: |
            The location of the Security Scheme to which the requirement
            resolves, or `null` if the scheme is unresolvable
        type: [string, "null"]
        format: uri-reference
```

For the single-document processing model, the equivalent single-document
OpenAPI Description is also provided.
