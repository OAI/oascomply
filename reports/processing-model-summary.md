# A Processing Model for the OpenAPI Specification

**Key Points:**

* Compliance tools and conformance test suites require well-defined, verifiable requirements
* The OAS lacks normative requirements for processing OpenAPI Descriptions
* The approach strongly implied by OAS/Swagger 2.0 conflicts with the normative requirements of JSON Schema in OAS 3.1
* The conflicts arise from reasonable, good-faith decisions spread out over time
* Clarifying and recommending a processing model in OAS 3.0.4 and 3.1.1 will improve interoperability and testability
* Moonwalk (OAS 4.0) is already moving in a direction that avoids these problems, and should follow through on that direction

## Introduction 

All implementations of the OpenAPI Specification (OAS) have a **processing model**, which is a set of steps that an implementation follows to interpret [OpenAPI Descriptions (OADs)](https://learn.openapis.org/introduction.html) before using them in some way.

Changes in the OAS from 2.0 to 3.0 to 3.1 produced requirements that conflict with common processing implementations.  Addressing those conflicts requires at least partially changing the processing model, which could be burdensome to implementers if not done carefully and with buy-in.

A compliance tool can only verify well-defined rules.  Ambiguity regarding referencing is a likely cause of inconsistent referencing support.  A clarified, consistent processing model will enable compliance tools, test suites, and better referencing support in general.

## Processing each OAS version

The current situation resulted from reasonable choices made by different people over several years.  No one person was in a position to notice everything needed to catch the conflicts.

OAS / Swagger 2.0 strongly implies a **reference-driven processing model**, in which each reference target is processed as an isolated JSON object in the context of the [entry document](https://learn.openapis.org/specification/structure.html).  In OAS 2.0 this produces well-defined results.

OAS 3.0 lacks such an implication.  Reference-driven processing still works, but there are more scenarios where the results might surprise OAD authors.

OAS 3.1 fully incorporates JSON Schema, which normatively requires a **document-driven processing model**.  Each complete JSON Schema document MUST be processed before references can be resolved from it.  Referenced schemas behave according to the context of the target document, not the referring document.  Using reference-driven processing here produces incorrect behavior, including behavior with security implications.

OAS 3.1 has Components Object sections for all referenceable types, and allows complete documents with Components but without Paths or Webhooks.  This makes it more suited to document-driven processing than OAS 3.0.

For more explanations and examples, see the [detailed report](processing-model-details.md).

## Recommendations

There is no one-size-fits-all solution for this problem.  We must work with the realities of tool development and existing adoption.  We must also balance user expectations regarding authorial intent, specification compliance, and tool stability.

In all cases, there will be many details to decide.  See the [detailed report](processing-model-details.md) for more information.

### OAS / Swagger 2.0:  Do nothing

OAS / Swagger 2.0 is only included in this report to explain the history.

### OAS 3.0: Clarify and recommend, but do not require

If most OAS 3.0 tools implement reference-driven processing in a consistent way, we should clarify that approach in an OAS 3.0.4 patch release.

If OAS 3.0 implementations vary widely, we may want to consider the options proposed for OAS 3.1 below.  Even if most use reference-driven processing, some might want to offer a 3.1-compatible approach to ease the transition to that version.

We will need to survey implementers to determine the best course of action.

### OAS 3.1: Clarify conformance requirements and provide well-defined options

OAS 3.1 support is still fairly new, and in many cases incomplete.  We need to survey implementers to find out if they support the more problematic cases, and how they handle them.  We may also need to understand whether implementers feel motivated to be in compliance, or whether they are likely to avoid implementing the features involved and document the omission.

OAS 3.1 can support a document-driven model with entry, Components-only, and standalone JSON Schema documents.  If implementers accept this, it would provide a consistent model across the whole 3.1 specification.

Otherwise, we can propose options such as a hybrid approach using a document-driven model only for Schema Objects.

### Moonwalk (OAS 4.0): Move ahead with the emerging document-driven model

Moonwalk has already made a decision to separate _importing_ documents from _referencing_ names within those documents, using namespaces to avoid conflicts.  This is already a document-driven processing model, so we only need to ensure that we follow through on its implications.

JSON Schema within Moonwalk would continue to use `"$ref"`, but already requires a document-driven approach.

### Media Types

The `application/openapi+json` and `application/openapi+yaml` media type registrations should be clarified to only apply to OpenAPI Description documents that consist of an OpenAPI Object at the document's root.

If documents consisting of other Objects from the OAS, or consisting of JSON or YAML that includes OAS Objects but is not overall in OAS format, are expected to be in the document ecosystem, then additional media types will be required.  These media types would need to be parameterized to inform parsers what syntax to expect.

### Workflows

The author of this report is not sufficiently familiar with the Workflows specification to make a recommendation, but it likely needs to make similar choices.

Since a Workflows implementation will need to work across (at least) both OAS 3.0 and 3.1 OADs, a consistent, or at least clearly-defined, processing model will lower the barrier to Workflows implementation and adoption.

## Summary

The OpenAPI Initiative now has an opportunity to provide guidance to implementers in a way that will increase interoperability across the tooling landscape.

The reference-driven approach of OAS 2.0 could be clarified for 3.0, and for non-Schema Object aspects of 3.1, but cannot serve as a model for 3.1 overall.  At least some incorporation of a document-driven processing model is required.

The OpenAPI Initiative needs to determine the degree to which document-driven processing can or should be adopted throughout OAS 3.1, and whether it should ever be recommended for OAS 3.0.  The OAI also needs to make decisions regarding the Workflows specification and OAS-related media types.
