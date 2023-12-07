# Link Object operationId resolution tests

Cases in this directory test the resolution of the `operationId` field
in the Link Object.  The resolution is shown in the outcome directories
by replacing each Link Object `operationId` with an `operationRef`
to the resolved operation.

Since `operationRef` cannot be inlined, and the Components Object does not
allow for storing Operation Objects, it is assumed that implementations
using a single-document model handle an `operationRef` by including enough
of the containing Path Item in the resulting singled-document OAD's
Paths Object, even if that Path Item Object is not otherwise referenced.

If any `operationId`s are not resolvable under the given processing model,
a `resolved.yaml` file will be present, conforming to the following JSON Schema:

```YAML
$schema: https://json-schema.org/draft/2020-12/schema

type: object
minProperties: 1

propertyNames:
  $comment: The URI-reference location of a Link Object's `operationId`
  type: string
  format: uri-reference

additionalProperties:
  $comment: The resolved object location, or `null` if unresolvable
  type: [string, "null"]
  format: uri-reference
```
