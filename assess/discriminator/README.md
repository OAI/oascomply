# Discriminator resolution cases

Discriminator resolution is shown by adding a complete `mapping` field
to the Discriminator Object in the output directories, mapping all possible
values (documented in an `enum` in the containing Schema Object) to
unambiguous URI-references.

The `"allOf"` form of the Discriminator Object is unusual because
it's possible (and even likely) that child schemas in non-entry documents
are not reachable through primary references from the entry document.
This means that implementations have to search the Components Object(s)
for them separately, and therefore have to decide where to look.

If a case cannot be resolved under a particular processing model,
a `resolved.yaml` file will be present, conforming to this JSON Schema:

```YAML
$schema: https://json-schema.org/draft/2020-12/schema
type: object

propertyNames:
    $comment: The location of the discriminator object in question
    type: string
    format: uri-reference

additionalProperties:
    $comment: Objects showing the resolution of each possible value
    type: object

    propertyNames:
        $comment: The location of the enumerated value being resolved
        type: string
        format: uri-reference

    additionalProperties:
        $comment: The resolution for the enumerated value
        type: object

        required: [value, resolution, expected]
        properties:
            value:
                $comment: The value in the instance
                type: string
            resolution:
                $comment: |
                    The processed (actual) location of the matching schema,
                    or `null` if none could be found with this processing model
                type: [string, "null"]
                format: uri-reference
            expected:
                $comment: The expected location of the matching schema
                type: string
                format: uri-reference
        additionalProperties: false
```
