# Object Type Reference Conflict Cases

These cases illustrate how an implementation might end up treating
the same JSON or YAML object as having two different types.  We use
an empty object as that is valid as both a Path Item Object and as
a Schema Object.

As with other test case groups, these cases have an `in` directory with
a multi-document OpenAPI Description (OAD).

Unlike other groups, instead of several output directories, there is just
a single `resolved.yaml`.  This shows the possible resolution of the
references, which always imply at least two type (e.g. Path Item vs Schema)
for at least one of the target.

Whether these conflicting types are considered an error depends on both
the implementation's processing model and its error detection and handling
logic.  The point of these cases is to determine how existing OAS tools
handle such scenarios.  This will help clarify various possible behaviors
as either bugs or features.

The `resolved.yaml` file conforms to the following JSON Schema:

```YAML
$schema: https://json-schema.org/draft/2020-12/schema
type: array
items:
    $comment: |
        Each item in the array documents a single reference target and
        the types it can have based on where it is and how it is reached
        via one or more references

    type: object
    required:
      - target
      - sources

    properties:
        target:
            $comment: |
                The type of a reference target based on its document
                context, or `null` if the document is not not a well-formed
                OAS document with an OpenAPI Object at the root
            $ref: "#/$defs/mapping"
            maxProperties: 1
        sources:
            $comment: |
                Maps a reference source to the type that it implies for
                this item's target
            $ref: "#/$defs/mapping"
        fromParent:
            $comment: |
                Maps the source from a *different* item in this resolved.yaml
                file to the type that it implies for *this* target due to this
                target being a child of the other item's target
            $ref: "#/$defs/mapping"
$defs:
    mapping:
        type: object
        minProperties: 1
        propertyNames:
            $comment: A location in an input file
            type: string
            format: uri-reference
        additionalProperties:
            $comment: |
                The object type of the location in some context, which
                may be `null` if the context does not provide enough
                information.
            type: [string, null]
            examples:
              - Schema
              - Path Item
              - Operation
```

