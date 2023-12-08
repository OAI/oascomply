# JSON Schema base URI bypassing tests

These tests assess whether references to the interior of a JSON Schema
document correctly take into account how `"$id"` in parent schema objects
changes the base URI for `"$ref"`.

The outcome directories hold a `resolved.yaml` file that shows the possible,
expected, and processed (actual) base URIs and the resulting resolved reference
URIs, and indicates whether the resolution is valid according to the JSON
Schema specificaiton or not.  These files conform to the following JSON Schema:

```YAML
$schema: https://json-schema.org/draft/2020-12/schema
type: array
items:
    type: object
    required:
      - source
      - uriReference
      - baseUriSources
      - baseUri
      - resolvedUri
      - valid
    properties:
        source:
            $comment: The reference location in the input files
        type: string
            format: uri-reference
        uriReference:
            $comment: The value of the reference, as it appears in the input
            type: string
            format: uri-reference
        baseUriSources:
            $comment: |
                The possible base URIs according to each source documented in
                a subsection of RFC 3986 §5.1; the lowest-numbered subsection
                with a non-`null` value is the correct base URI.  Note that
                the application-level default base URI field is included for
                completeness only, and is not relevant to these cases.
            type: object
            required:
              - rfc3986_5.1.1_inContent
              - rfc3986_5.1.2_encapsulatingEntity
              - rfc3986_5.1.3_retrievalUri
              - rfc3986_5.1.4_applicationDefault
            propertyNames:
                enum:
                  - rfc3986_5.1.1_inContent
                  - rfc3986_5.1.2_encapsulatingEntity
                  - rfc3986_5.1.3_retrievalUri
                  - rfc3986_5.1.4_applicationDefault
            additionalProperties:
                type: string
                format: uri
        baseUri:
            type: object
            required: [expected, processed]
            properties:
                expected:
                    $comment: The RFC 3986-determined base URI
                    type: string
                    format: uri
                processed:
                    $comment: The base URI determined by the processing model
                    type: string
                    format: uri
            additionalProperties: false
        resolvedUri:
            $comment: |
                The fully resolved reference URI (the `uriReference` field
                resolved against the `processed` `baseUri` field).
            type: string
            format: uri
        valid:
            $comment: |
                Whether this resolve URI is valid according to the JSON Schema
                draft 2020-12 specification
            type: boolean
```
