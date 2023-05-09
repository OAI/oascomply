# OpenAPI Compliance

This repository contains the OpenAPI Compliance Project, the first
piece of which is the OpenAPI Specification Compliance Parser.

The OAS Compliance Parser is expected to reach 1.0 status by
late 2023.  The current status of the project is
[pre-Milestone 1](https://tinyurl.com/4kth84k8)

## Requirements and Installation

`oascomply` is a Python package with several command-line interfaces,
most notably the `oascomply` command.

### Terminology and typographical conventions

Examples in this documentation use MacOS conventions unless otherwise noted:

* `directory-name %` is a command line prompt
* `/Users/someone` is the home directory of user `someone`

Terminology around URLs, URIs, and IRIs is distressingly confusing.
Various sections below explain why each term is used in specific places,
and why and how it matters.  In general:

* ***URLs*** are for retrievable things
* ***URIs*** are for identifiers not intended to be directly retrieved,
             even if it is possible to retrieve them
* ***IRIs*** indicate URIs or URLs with full unicode support; whether
             a specific usage of "IRI" corresponds to a URL or a URI
             should be clear from context.  ~~"IRL"~~ is not a term that
             is defined or used by any standard.

This documentation uses the term ***non-relative URL*** (or
***non-relative URI*** or ***non-relative IRI***) to describe a URL/URI/IRI
that MUST start with a scheme (e.g. `https:`, `file:`, `urn:`, etc.) and
MAY include a fragment (e.g. `#3.0-PathItem`, `#/components/schemas/foo`).[^nonrel]

The usage of ***URL*** (for things that are retrieved from the address) vs
***URI*** (for identifiers not assumed to be retrievable, which may or
may not actually _be_ retrievable) vs ***IRI*** (for either use case,
but with full unicode support) are explained as needed in various sections
below, with examples to clarify whether and why it matters in each case.

Please note that URLs are assumed to comply with RFC 3986, and not
WHATWG's URL "Living Standard", which is a parsing/serialization specification
for web browsers.  If you don't know what this means, consider yourself lucky.
If you are curious,
[Roy Fielding weighed in on the mess](https://lists.w3.org/Archives/Public/ietf-http-wg/2022AprJun/0173.html)
in 2022.

### Installing Python

`oascomply` requires Python 3.8 or later.  Python.org provides installation
instructions for [Windows](https://docs.python.org/3.11/using/windows.html)
(through either the Python site or the
[Microsoft Store](https://devblogs.microsoft.com/python/python-in-the-windows-10-may-2019-update/))
and [Mac OS](https://docs.python.org/3.11/using/mac.html)
(through the Python site).

If your system has an older version of Python, you can use
[`pyenv`](https://github.com/pyenv/pyenv/blob/master/README.md),
[`pyenv` for Windows](https://github.com/pyenv-win/pyenv-win/blob/master/README.md),
or another similar tool to install an appropriate version.

_Note: At this stage, `oascomply` has only been tested with Python 3.8 on
Mac OS 12.6 on an Apple M1 chip.  Automated testing across Python 3.8-3.12
will be added prior to publication.  No support for earlier Python versions
will be added due to the requirements of various dependencies.  Please
contact the maintainer if you can help with Windows testing._

### Installing `oascomply` with `pip`

`oascomply` is not yet available through pypi.org, and therefore
not yet installable with `pip`

### Installing `oascomply` from GitHub with `poetry`

Currently, `oascomply` must be checked out from GitHub and installed
using [`poetry`](https://python-poetry.org/docs/).

```ShellSession
src % curl -sSL https://install.python-poetry.org | python3 -
src % git clone https://github.com//OAI/oascomply.git
src % cd oascomply
oascomply % poetry install
```

This keeps all of the `oascomply` dependencies in their own environment,
which you can access with
[`poetry shell`](https://python-poetry.org/docs/cli/#shell).  Alternatively,
you can prefix each command that you want to run with
[`poetry run`](https://python-poetry.org/docs/cli/#run), e.g.:

```ShellSession
oascomply % poetry run python oascomply -h
```

Note that all `poetry` commands need to be run from inside
the repository directory, as `poetry` determines what environment
to use by looking in the current directory and its parent
directories for a `pyproject.toml` file.  Otherwise you will
see an error like this:

```ShellSession
src % poetry run python oascomply -h

Poetry could not find a pyproject.toml file in /Users/someone/src or its parents
```

## YAML vs JSON API descriptions

`oascomply` supports both YAML and JSON description files.  However, performance
is substantially better with JSON, and source file line and column mapping is
more reliable.

See [issue #9](https://github.com/handrews/oasparser/issues/9)
to track performance improvements for YAML, and
[issue #11](https://github.com/handrews/oasparser/issues/11)
to track the status of the YAML source file line and column mapping feature.

Note also that some public YAML OpenAPI files do not quote values properly,
causing them to be interpreted as `datetime` objects or other types that do
not fit the JSON data model.  Such API descriptions are not compliant with
the OAS, and are not supported by `oascomply`.  Please file any issues with
the API description file maintainers.

## Usage: Parsing API descriptions

In the simplest case of a single API description file in either YAML or
JSON, where all references (`$ref` or `operationRef`) start with `#`
(e.g. `"$ref": "#/components/schemas/foo"`), you can just pass the
file to `oascomply` and everything will work fine:

```ShellSession
oascomply % oascomply -f openapi.yaml
```

The `oascomply` output format will refer to this file using the corresponding
`file:` URL.  If this file is in the directory `/Users/someone/src/`,
then the URL will be `file:///Users/someone/src/openapi.yaml`[^fileurls]

Currently `oascomply` only works on local files; this may change in the future.

### Showing more useful output: URLs vs URIs

Your local `file:` URL might not be useful when sharing output with others.
In the example above, `openapi.yaml` is not informative, and if your team
is working on multiple APIs, it's not clear what repository or branch
you have checked out under `/Users/someone/src`.  Or even whether it's
a source control repository or just a local copy of some file.

`oascomply` lets you set a URI for use in output in place of the URL.  If
your API description document is normally deployed at a network URL
(which `oascomply` doesn't yet understand how to load directly), you can
pass it that URI after the file name:

```ShellSession
oascomply % oascomply -f openapi.yaml https://example.com/coolapi/openapi
```

`oascomply` understands that location and identification are often separate.
It will use the **URI** (in the above example, an `https:` URL) in most places.  
However, that URI will be associated with the loaded **URL** through
a `locatedAt` relationship for debugging convenience.

This also allows assigning situation-specific URIs, such as a URL for a
specific revision of a file in git rather than the publicly deployed version.

### Loading multi-document API descriptions

Referencing and multi-document API descriptions are fully supported
by `oascomply` (3.0 currently supported, 3.1 support in progress).

For security reasons, `oascomply` will not automatically fetch
referenced documents (see
[issue #1](https://github.com/handrews/oasparser/issues/1) for progress
on security features).  Instead, it must be informed of all relevant
documents up front, which in most cases can be done simply by repeating
the '-f' option:

```ShellSession
oascomply % oascomply -f openapi.yaml -f schemas/foo.yaml -f schemas/bar.yaml
```

URLs vs URIs are important for reference resolution:  `oascomply` expects
references to point to each document's ***URI***, for several reasons:

* Best practices for referencing should omit any file extension to ensure
  that the same file contents work in both JSON and YAML
* `oascomply` supports setting the URI on the command line, but always
  sets the URL based on the document location

So if our `openapi.yaml` file has references like `"$ref": "schemas/foo"`
and `"$ref": "schemas/bar"`, and all of the files are normally found
under `https://example.com/coolapi` without file extensions, then we'll
want to do the following:

```ShellSession
oascomply % oascomply \
    -f openapi.yaml https://example.com/coolapi/openapi \
    -f schemas/foo.yaml https://example.com/coolapi/schemas/foo \
    -f schemas/bar.yaml https://example.com/coolapi/schemas/bar
```

That's awfully wordy, so the '-d' option lets you map a directory to
a URI prefix[^iriprefix], and all files under that directory will have their
URIs constructed by replacing the directory with the prefix and removing any
file extension.  Note that the URI prefix MUST end with a path ending in '/'
to match the directory behavior.  So this command line has the same effect
as the one above:

```ShellSession
oascomply % oascomply -d . https://example.com/coolapi/ \
    -f openapi.yaml -f schemas/foo.yaml -f schemas/bar.yaml
```

_The following feature will be added in the future:_

_Since all of our files use the same prefix mapping, as long as they are the
only `.json`, `.yaml`, or `.yml` files anywhere under that directory, we can
reduce this further with '-D', which automatically loads everything it can find
under the mapped directory:_

```ShellSession
oascomply % oascomply -D . https://example.com/coolapi/  # NOT YET SUPPORTED
```

### Handling complex multi-document referencing

Certain use cases that are most likely to come up with bundled external schemas
with OAS 3.1, require passing some extra information to `oascomply` in order to
handle them correctly.

When parsing multiple documents, `oascomply` looks for the file that has an
`openapi` property at the root and starts there.  As it finds `$ref`s to other
documents, it knows what sort of OpenAPI object (e.g. Schema Object,
Parameter Object, etc.) to parse and validate in that document based on where
it found the `$ref`.

In OAS 3.0, this should be sufficient _(I think... TBD)_, because even though
there are other types of references, such as using `operationId` to target
callbacks, the structures containing those reference targets also need to be
linked into the main structure through `$ref`.

However, in OAS 3.1, Schema Objects can use the `$anchor`, `$dynamicAnchor`,
and `$id` keywords to define URIs that do not match the URL _or_ URI for the
document, no matter how you set the document's URI.  If there is _also_
a `$ref` using the document's assigned URI, then `oascomply` will find and
use these keyword-defined URIs correctly.  But if not, we need to tell
`oascomply` how to interpret these documents on the command line.

Let's add another schema document, `schemas/things.yaml`, to our example
from before, with the following contents:

```YAML
$schema: https://json-schema.org/draft/2020-12/schema
$id: https://example.com/coolapi/schemas/things
$defs:
    thing1:
        $id: thing1
        type: integer
    thing2:
        $id: thing2
        type: string
```

This is the sort of schema you get when you bundle several individual schemas,
each with their own `$id`, into a single document.  The root schema is not
useful as it doesn't define any constraints.  It's just a container for `$defs`.

Usually, when you bundle schemas, you want to keep using the same `$id`s that
were present in the un-bundled schemas, because bundling and un-bundling
shouldn't require you to update your references.  It's just an implementation
detail of the file structure.  So in our main document (the one with the
`openapi` field), our references would look like `"$ref": "schemas/thing1"`
and `"$refs": "schemas/thing2`.

If we just use the `-D` option, it will notice `schemas/things.yaml` but
never attempt to parse it because it's never referenced directly.  Even though
`oascomply` knows it is relevant, it doesn't know what part of the OAS 3.0
schema to use to validate it.  It could make an assumption based on the
presence of `"$schema"`, but since `oascomply` is all about compliance, it
avoids making "helpful" guesses that might hide an error.

So let's go back to using `-f` for each file, and add semantic type information
to this file:

```ShellSession
oascomply % oascomply \
    -f openapi.yaml https://example.com/coolapi/openapi \
    -f schemas/foo.yaml https://example.com/coolapi/schemas/foo \
    -f schemas/bar.yaml https://example.com/coolapi/schemas/bar \
    -f schemas/things.yaml https://example.com/coolapi/schemas/things 3.1-Schema
```

That `3.1-Schema` comes from the semantic types that you see in the output from
`oascomply`.  The full type is a URI,
`https://openapis.org/compliance/ontology#3.1-Schema`, but we just need the
fragment (the part after the `#`) here.  This tells `oascomply` to parse
the document with the OAS 3.1 Schema Object (meta-)schema, without waiting
for a `$ref` to reference it first.

Since the document URIs are still regular, we can still shorten this with `-d`:

```ShellSession
oascomply % oascomply -d . https://example.com/coolapi/ \
    -f openapi.yaml -f schemas/foo.yaml -f schemas/bar.yaml \
    -f schemas/things.yaml 3.1-Schema
```

Here, it's a good thing that `3.1-Schema` can't be mistaken for a non-relative
URI!

_In the future, it should be possible to use this with `-D` as well, and
only use `-f` for the one file that needs semantic type information:_

```ShellSession
oascomply % oascomply -D . https://example.com/coolapi/ \  # NOT YET SUPPORTED
    -f schemas/things.yaml 3.1-Schema                      # NOT YET SUPPORTED
```

-----

[^nonrel]: The choice of "non-relative URL/URI/IRI" is to avoid confusion
around the terms "URL", "URI", and "IRI", which
are imprecise in everyday usage, and the term "absolute URL/URI/IRI", which
probably doesn't mean what you think it means (it is non-relative, but also
forbids fragments).  This documentation does _not_ use the more technically
correct term "URL/URI/IRI reference" because it is unfamiliar to most people,
and a bit unwieldy.  For those who know the standards terminology, this
documentation uses ***relative URL***/***URI***/***IRI*** in place of the
more technically correct "relative URL/URI/IRI reference".

[^fileurls]: As explained in
[RFC 8089 Appendix B](https://datatracker.ietf.org/doc/html/rfc8089#appendix-B),
`file:/foo/bar` and `file:///foo/bar` indicate the same filesytem path.
As the empty authority (`file:///`) form is more common, and some libraries
might not handle the no-authority (`file:/`) form correctly, `oascomply`
endeavors to use `file:///` consistently.

[^iriprefix]: The URI prefix can be an IRI prefix as far as `oascomply` is
concerned, but OAS 3.x and JSON Schema 2020-12 do not allow IRIs to appear
directly, so depending on how your references are written, you may need to
encode any IRI down to a URI as described in RFC 3987.  IRIs are accepted
mostly as future-proofing for presumed eventual IRI support in OAS.
