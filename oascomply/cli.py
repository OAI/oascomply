import argparse
import json
from pathlib import Path
from typing import (
    Any, Iterator, Mapping, Optional, Sequence, Tuple, Type, Union
)
import logging
import sys

import oascomply
from oascomply.oassource import (
    DirectMapSource, FileMultiSuffixSource, HttpMultiSuffixSource,
)
from oascomply.apidescription import ApiDescription
from oascomply.serializer import OASSerializer
from oascomply.resource import (
    OASResourceManager, URI, URIError,
    ThingToURI, PathToURI, URLToURI,
)


logger = logging.getLogger(__name__)


HELP_PROLOG = """
Load and validate an API Description/Definition (APID).

The initial APID document is parsed immediately, with other documents parsed
as they are referenced.  The initial document is the first of:

1. The document from -i (--initial-resource), which takes a URI (like "$ref")
2. The first document from a -f (--file) containing an "openapi" field
3. The first document from a -u (--url) containing an "openapi" field

Each document's URL is the URL from which it was retrieved. If loaded from
a local filesystem path, the URL is the corresponding "file:" URL.

A document's URI is either determined from the URL (potentially as modified
by the -x, -D, and -P options), or set directly on the command line
(using additional arguments to -f, -u, -d, or -p)..
This allows reference resolution to work even if the documents are not named
or deployed in the way the references expect.

See the "Loading APIDs and Schemas" tutorial for full documentation.
"""


HELP_EPILOG = """
See the README for further information on:

* How API description data appears in the output
* How to extract human-friendly names from the output
* API description document URLs vs URIs
* Handling multi-document API descriptions
* Handling complex referencing scenarios
"""


DEFAULT_SUFFIXES = ('.json', '.yaml', '.yml', '')  # TODO: not sure about ''
"""Default suffixes stripped from -f paths and -u URLs"""


def _add_verbose_option(parser):
    parser.add_argument(
        '-v',
        '--verbose',
        action='count',
        default=0,
        help="Increase verbosity; can passed twice for full debug output.",
    )


def _add_strip_suffixes_option(parser):
    parser.add_argument(
        '-x',
        '--strip-suffixes',
        nargs='*',
        default=DEFAULT_SUFFIXES,
        help="For documents loaded with -f or -u without an explict URI "
            "assigned on the command line, assign a URI by stripping any "
            "of the given suffixes from the document's URL; passing this "
            "option without any suffixes disables this behavior, treating "
            "the unmodified URL as the URI; the default stripped suffixes "
            "are .json, .yaml, .yml",
    )


class CustomArgumentParser(argparse.ArgumentParser):
    def _fix_message(self, message):
        # nargs=+ does not support metavar=tuple
        return message.replace(
            'FILES [FILES ...]',
            'FILE [URI] [TYPE]',
        ).replace(
            'DIRECTORIES [DIRECTORIES ...]',
            'DIRECTORY [URI_PREFIX]',
        ).replace(
            'URLS [URLS ...]',
            'URL [URI] [TYPE]',
        ).replace(
            'PREFIXES [PREFIXES ...]',
            'URL_PREFIX [URI_PREFIX]',
        )

    def format_usage(self):
        return self._fix_message(super().format_usage())

    def format_help(self):
        return self._fix_message(super().format_help())


class ActionAppendThingToURI(argparse.Action):
    @classmethod
    def make_action(
        cls,
        arg_cls: Type[ThingToURI] = ThingToURI,
        strip_suffixes: Sequence[str] = (),
    ):
        logger.debug(f'Registering {arg_cls.__name__} argument action')
        return lambda *args, **kwargs: cls(
            *args,
            arg_cls=arg_cls,
            strip_suffixes=strip_suffixes,
            **kwargs,
        )

    def __init__(
        self,
        option_strings: str,
        dest: str,
        *,
        nargs: Optional[str] = None,
        arg_cls: Type[ThingToURI],
        strip_suffixes: Sequence[str],
        **kwargs
    ) -> None:
        if nargs != '+':
            raise ValueError(
                f'{type(self).__name__}: expected nargs="+"'
            )
        self._arg_cls = arg_cls
        self._strip_suffixes = strip_suffixes
        super().__init__(option_strings, dest, nargs=nargs, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        arg_list = getattr(namespace, self.dest)
        arg_list.append(
            self._arg_cls(values, strip_suffixes=self._strip_suffixes),
        )


def parse_logging() -> Sequence[str]:
    """
    Parse logging options and configure logging before parsing everything else.

    Without doing this first, we lose valuable logging from the custom arg
    handling classes.  Note that the options are re-added to the main parsing
    pass so that they appear in the help output.
    """
    verbosity_parser = argparse.ArgumentParser(add_help=False)
    _add_verbose_option(verbosity_parser)
    v_args, remaining_args = verbosity_parser.parse_known_args()

    oascomply_logger = logging.getLogger('oascomply')
    if v_args.verbose:
        if v_args.verbose == 1:
            oascomply_logger.setLevel(logging.INFO)
        else:
            oascomply_logger.setLevel(logging.DEBUG)
    else:
        oascomply_logger.setLevel(logging.WARNING)
    return remaining_args


def parse_non_logging(remaining_args: Sequence[str]) -> argparse.Namespace:
    """
    Parse everything except for logging and return the resulting namespace.
    """

    # First parse out the strip suffixes option because it is used
    # to configure how other args are parsed.
    strip_suffixes_parser = argparse.ArgumentParser(add_help=False)
    _add_strip_suffixes_option(strip_suffixes_parser)
    ss_args, remaining_args = strip_suffixes_parser.parse_known_args(
        remaining_args,
    )

    parser = CustomArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=HELP_PROLOG,
        epilog=HELP_EPILOG,
        fromfile_prefix_chars='@',
    )
    # Already parsed, but add to include in usage message
    _add_verbose_option(parser)
    parser.add_argument(
        '-i',
        '--initial',
        help="The URI of the document from which to start validating.  "
             "If not present, the first -f argument is used; if no -f "
             "arguments are present, the first -u argument is used."
    )
    parser.add_argument(
        '-f',
        '--file',
        nargs='+',
        action=ActionAppendThingToURI.make_action(
            arg_cls=PathToURI,
            strip_suffixes=ss_args.strip_suffixes,
        ),
        default=[],
        dest='files',
        help="An APID document as a local file, optionally followed by a URI "
             "to use for reference resolution; if no URI is provided but the "
             "file matches a directory passed with -d, its URI will be "
             "determined based on the -d URI prefix (and -D if present); "
             "if no -d matches, the corresponding 'file:' URL for the path "
             "will be used as the URI; this option can be repeated; "
             "see also -x, -d, -D",
    )
    parser.add_argument(
        '-u',
        '--url',
        nargs='+',
        action=ActionAppendThingToURI.make_action(
            arg_cls=URLToURI,
            strip_suffixes=ss_args.strip_suffixes,
        ),
        default=[],
        dest='urls',
        help="A URL for an APID document, optionally followed by a URI "
             "to use for reference resolution; if no URI is provided but the "
             "url matches a prefix passed with -p, its URI will be determined "
             "based on the -p URI prefix (and -P if present); if no -p "
             "matches, the URL will also be used as the URI; currently only "
             "'http:' and 'https:' URLs are supported; this option can be "
             "repeated; see also -x, -p, -P",
    )
    # Already parsed, but add to include in usage message
    _add_strip_suffixes_option(parser)
    parser.add_argument(
        '-d',
        '--directory',
        nargs='+',
        action=ActionAppendThingToURI.make_action(arg_cls=PathToURI),
        default=[],
        dest='directories',
        help="Resolve references matching the URI prefix from the given "
            "directory; if no URI prefix is provided, use the 'file:' URL "
            "corresponding to the directory as the prefix; this option "
            "can be repeated; see also -D",
    )
    parser.add_argument(
        '-p',
        '--url-prefix',
        nargs='+',
        action=ActionAppendThingToURI.make_action(arg_cls=URLToURI),
        default=[],
        dest='url_prefixes',
        help="Resolve references the URI prefix by replacing it with "
            "the given URL prefix, or directly from URLs matching the "
            "URL prefix if no URI prefix is provided; this option can be "
            "repeated; see also -P",
    )
    parser.add_argument(
        '-D',
        '--directory-suffixes',
        nargs='*',
        default=('.json', '.yaml', '.yml'),
        dest='dir_suffixes',
        help="When resolving references using -d, try appending each "
            "suffix in order to the file path until one succeeds; "
            "the empty string can be passed to try loading the "
            "unmodified path first as JSON and then if that fails as "
            "YAML; the default suffixes are .json, .yaml .yml",
    )
    parser.add_argument(
        '-P',
        '--url-prefix-suffixes',
        nargs='*',
        default=(),
        dest='url_suffixes',
        help="When resolving references using -p, try appending each "
            "suffix in order to the URL until one succeeds; the empty "
            "string can be passed to try loading the unmodified URL "
            "which will be parsed based on the HTTP Content-Type header; "
            "by default, no suffixes are appended to URLs",
    )
    parser.add_argument(
        '-n',
        '--number-lines',
        action='store_true',
        help="Enable line and column numbers in the graph and in "
             "error reporting; this has a considerable performance "
             "impact, especially for YAML",
    )
    parser.add_argument(
        '-e',
        '--examples',
        choices=('true', 'false'),
        default='true',
        help="Pass 'false' to disable validation of examples and defaults "
             "by the corresponding schema.",
    )
    parser.add_argument(
        '-o',
        '--output-format',
        nargs='?',
        const='nt11',
        metavar="nt | ttl | n3 | trig | json-ld | xml | hext | ...",
        help="Serialize the parsed graph to stdout in the given format, "
             "or 'nt11' (N-Triples with UTF-8 encoding) if no format name "
             "is provided.  Format names are passed through to rdflib, "
             "see that library's documentation for the full list of "
             "options.",
    )
    parser.add_argument(
        '-O',
        '--output-file',
        help="NOT YET IMPLEMENTED "
             "Write the output to the given file instead of stdout",
    )
    parser.add_argument(
        '--test-mode',
        action='store_true',
        help="Omit data such as 'locatedAt' that will change for "
             "every environment and produce sorted nt11 output.  "
             "This is intended to facilitate "
             "automated testing of the entire system.",
    )

    args = parser.parse_args(remaining_args)

    logger.debug(f'Processed arguments:\n{args}')

    # TODO: This does not seem to work at all - fix or toss?
    # Note that if -P or -D are actually passed with
    # the args matching the default, this check will
    # still work as they will be set as a list instead
    # of the default values which are tuples
    for attr, opt, check in (
        ('initial', '-i', lambda arg: True),
        ('urls', '-u', lambda arg: True),
        ('url_prefixes', '-p', lambda arg: True),
        ('dir_suffixes', '-D', lambda arg: arg == (
            '.json', '.yaml', '.yml',
        )),
        ('url_suffixes', '-P', lambda arg: arg == ()),
        ('output_file', '-O', lambda arg: True),
    ):
        if hasattr(args, attr) and not check(getattr(args, attr)):
            raise NotImplementedError(f'{opt} option not yet implemented!')

    return args


def load():
    remaining_args = parse_logging()
    args = parse_non_logging(remaining_args)
    manager = OASResourceManager(
        oascomply.catalog,
        files=args.files,
        urls=args.urls,
        directories=args.directories,
        url_prefixes=args.url_prefixes,
        dir_suffixes=args.dir_suffixes,
        url_suffixes=args.url_suffixes,
    )
    serializer = OASSerializer(
        output_format=args.output_format,
        test_mode=args.test_mode,
    )

    # TODO: Temporary hack, search lists properly
    # TODO: Don't hardcode 3.0
    entry_resource = manager.get_entry_resource(
        args.initial,
        oasversion='3.0',
    )
    if entry_resource is None:
        sys.stderr.write(
            'ERROR: '
            'oascomply requires either -i (--initial-resource) along with '
            'at least one of -d (--directory) or -p (--url-prefix). OR at '
            'least one of -f (--file) or -u (--url)\n',
        )
        sys.exit(-1)

    if 'openapi' not in entry_resource:
        sys.stderr.write('ERROR: The initial document must contain "openapi"\n')
        sys.exit(-1)

    desc = ApiDescription(
        entry_resource,
        resource_manager=manager,
        test_mode=args.test_mode,
    )

    errors = desc.validate(validate_examples=(args.examples == 'true'))
    if errors:
        return report_errors(errors)
    errors.extend(desc.validate_graph())
    if errors:
        return report_errors(errors)

    if args.output_format is not None or args.test_mode is True:
        serializer.serialize(
            desc.get_oas_graph(),
            base_uri=str(desc.base_uri),
            resource_order=[str(v) for v in desc.validated_resources],
        )

    sys.stderr.write('Your API description is valid!\n')


def report_errors(errors):
    for err in errors:
        logger.critical(
            f'Error during stage "{errors["stage"]}"' +
            (
                f', location <{errors["location"]}>:'
                if errors.get('location', 'TODO') != 'TODO'
                else ':'
            )
        )
        logger.critical(json.dumps(err['error'], indent=2))

    sys.stderr.write('\nAPI description contains errors\n\n')
    sys.exit(-1)
