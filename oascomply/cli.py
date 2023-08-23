import argparse
import json
from pathlib import Path
from typing import (
    Any, Iterator, Mapping, Optional, Sequence, Tuple, Type, Union
)
import logging
import sys

import jschon
import jschon.exc

import oascomply
from oascomply.oassource import (
    DirectMapSource, FileMultiSuffixSource, HttpMultiSuffixSource,
)
from oascomply.apidescription import OASResourceManager, ApiDescription
from oascomply.serializer import OASSerializer


logger = logging.getLogger(__name__)


HELP_PROLOG = """
Load and validate an API Description/Definition (APID).

The initial APID document is parsed immediately, with other documents parsed
as they are referenced.  The initial document is the first of:

1. The document from -i (--initial-document)
2. The first document from a -f (--file) containing an "openapi" field
3. The first document from a -u (--url) containing an "openapi" field

All referenced documents MUST be provided in some form on the command line,
either individually (with -f or -u) or as a document tree to search (with
-d or -p).  Documents are loaded from their URL and referenced by their URI.

Each document's URL is the URL from which it was retrieved. If loaded from
a local filesystem path, the URL is the corresponding "file:" URL.

A document's URI is either determined from the URL (potentially as modified
by the -x, -D, and -P options), or set directly on the command line
(using additional arguments to -i, -f, -u, -d, or -p)..
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
        default=('.json', '.yaml', '.yml', ''),  # TODO: not sure about ''
        help="For documents loaded with -f or -u without an explict URI "
            "assigned on the command line, assign a URI by stripping any "
            "of the given suffixes from the document's URL; passing this "
            "option without any suffixes disables this behavior, treating "
            "the unmodified URL as the URI; the default stripped suffixes "
            "are .json, .yaml, .yml",
    )


class ThingToURI:
    """
    Helper class for mapping URIs to URLs and back.

    In addition to being more convenient than a tuple or dict, this class
    hierarchy handles calculating URIs from things based on various factors.

    :param values: A string or sequence of strings as in the
        :class:`argparse.Action` interface
    :param strip_suffixes: The suffixes, if any, to strip when determining
        a URI from the thing
    :param uri_is_prefix: Indicates that the URI will be used as a prefix,
        which currently requires it to have a path ending in "/".
    """
    def __init__(
        self,
        values: Union[str, Sequence[str]],
        strip_suffixes: Sequence[str] = (),
        uri_is_prefix: bool = False,
    ) -> None:
        logger.debug(
            f'Parsing location+uri option with argument {values!r}, '
            f'stripping suffixes: {strip_suffixes}',
        )
        try:
            if isinstance(values, str):
                values = [values]
            if len(values) not in (1, 2):
                raise ValueError(f'Expected 1 or 2 values, got {len(values)}')

            self._auto_uri = len(values) == 1
            self._values = values
            self._to_strip = strip_suffixes
            self._uri_is_prefix = uri_is_prefix

            thing = self._set_thing(values[0])
            if len(values) == 2:
                uri_str = values[1]
                logger.debug(
                    f'Using URI <{uri_str}> from command line for "{thing}"'
                )
            else:
                uri_str = self._uri_str_from_thing(
                    self._strip_suffixes(thing),
                )
                logger.debug(
                    f'Calculated URI <{uri_str}> for "{thing}"'
                )

            uri_obj = jschon.URI(uri_str)
            if uri_is_prefix and not uri_obj.path.endswith('/'):
                raise ValueError(
                    f"URI prefix <{uri_str}> must have a path ending in '/'",
                )

            self.set_uri(uri_str)

            if uri_is_prefix and uri_obj.query or self.uri.fragment:
                raise ValueError(
                    f"URI prefix <{self.uri}> may not include "
                    "a query or fragment",
                )

            logger.info(str(self))

        except Exception:
            # argparse suppresses any exceptions that are raised, so log them
            import traceback
            from io import StringIO

            buffer = StringIO()
            traceback.print_exc(file=buffer)
            logger.warning(buffer.getvalue())

            raise

    def __repr__(self):
        return (
            f'{self.__class__.__name__}('
            f'{self._values!r}, {self._to_strip!r}, {self._uri_is_prefix})'
        )

    def __eq__(self, other):
        if not isinstance(other, ThingToURI):
            return NotImplemented
        return self.thing == other.thing and self.uri == other.uri

    @property
    def thing(self):
        """
        Generic thing accessor; subclasses should offer a more specific one.

        See non-public :meth:`_set_thing` for modifications.
        """
        return self._thing

    @property
    def auto_uri(self):
        """
        True if this class generated a URI rather than receivingit as a param.
        """
        return self._auto_uri

    def __str__(self):
        return f'(thing: {self._values[0]}, uri: <{self.uri}>)'

    def _strip_suffixes(self, thing: Any) -> str:
        thing_string = str(thing)
        for suffix in self._to_strip:
            if thing_string.endswith(suffix):
                return thing_string[:-len(suffix)]
        return thing_string

    def _set_thing(self, thing_str) -> Any:
        self._thing = thing_str
        return thing_str

    def set_uri(
        self,
        uri_str: str,
        attrname: str = 'uri',
    ) -> None:
        uri = jschon.URI(uri_str)
        try:
            uri.validate(require_scheme=True)
            setattr(self, attrname, (uri))
        except jschon.exc.URIError as e:
            logger.debug(
                f'got exception from URI ({uri_str}):'
                f'\n\t{e}'
            )
            raise ValueError(f'{uri_str} cannot be relative')

    def _uri_str_from_thing(self, stripped_thing_str: str) -> str:
        return stripped_thing_str


class PathToURI(ThingToURI):
    """Local filesystem path to URI utility class."""

    def __str__(self):
        return f'(path: {self.path}, uri: <{self.uri}>)'

    def _set_thing(self, thing_str: str) -> None:
        self.path = Path(thing_str).resolve()
        if self._uri_is_prefix and not self.path.is_dir():
            raise ValueError(
                f"Path '{self.path}' must be a directory when mapping "
                "to a URI prefix",
            )
        return self.path

    def _uri_str_from_thing(self, stripped_thing_str: str) -> str:
        # It seems odd to rebuild the path object, but Path.with_suffix('')
        # doesn't care what suffix is removed, so we couldn't use it anyway
        # Also, arg parsing code does not need to be blazingly fast.
        path = Path(stripped_thing_str).resolve()

        # Technically, URI trailing slashes don't mean the same thing as
        # "directory", but that is the expectation of the dir mapping code.
        uri = path.as_uri()
        if path.is_dir() and self._uri_is_prefix and not uri.endswith('/'):
            uri += '/'

        return uri

    @property
    def path(self) -> Path:
        """Accessor for ``path``, the "thing" of this ThingToURI subclass."""
        return self._path

    @path.setter
    def path(self, p: Path) -> None:
        self._path = p

    @property
    def thing(self) -> Any:
        return self.path


class URLToURI(ThingToURI):
    """URL to URI utility class; does not check URL scheme or usability."""
    def __str__(self):
        return f'(url: <{self.url}>, uri: <{self.uri}>)'

    def _set_thing(self, thing_str: str) -> None:
        self.set_uri(thing_str, attrname='url')
        if self._uri_is_prefix and not self.url.path.endswith('/'):
            raise ValueError(
                f"URL prefix <{thing_str}> must have a path ending in '/'",
            )
        return self.url

    @property
    def url(self) -> jschon.URI:
        """Accessor for ``url``, the "thing" of this ThingToURI subclass."""
        return self._url

    @url.setter
    def url(self, u: jschon.URI) -> None:
        self._url = u

    @property
    def thing(self):
        return self.url


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
        help="An APID document as a local file, optionally followed by "
             "a URI to use for reference resolution in place of the "
             "corresponding 'file:' URL; this option can be repeated; "
             "see also -x",
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
             "to use for reference resolution; by default only 'http:' "
             "and 'https:' URLs are supported; this option can be "
             "repeated; see also -x",
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


def configure_manager(
    catalog: jschon.Catalog,
    *,
    files: Sequence[PathToURI],
    urls: Sequence[URLToURI],
    directories: Sequence[PathToURI],
    url_prefixes: Sequence[URLToURI],
    dir_suffixes: Sequence[str],
    url_suffixes: Sequence[str],
) -> OASResourceManager:
    manager = OASResourceManager(oascomply.catalog)

    for dir_to_uri in directories:
        manager.add_uri_source(
            dir_to_uri.uri,
            FileMultiSuffixSource(
                str(dir_to_uri.path), # TODO: fix type mismatch
                suffixes=dir_suffixes,
            )
        )

    for url_to_uri in url_prefixes:
        manager.add_uri_source(
            url_to_uri.uri,
            HttpMultiSuffixSource(
                str(url_to_uri.url), # TODO: fix type mismatch
                suffixes=url_suffixes,
            )
        )

    resource_map = {
        f_to_u.uri: f_to_u.path
        for f_to_u in files
    }
    resource_map.update({
        u_to_u.uri: u_to_u.path
        for u_to_u in urls
    })
    manager.add_uri_source(
        None,
        DirectMapSource(
            resource_map,
            suffixes=('.json', '.yaml', '.yml'),
        )
    )

    return manager


def load():
    remaining_args = parse_logging()
    args = parse_non_logging(remaining_args)
    manager = configure_manager(
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
    logger.debug(f'initial: <{args.initial}>')
    entry_resource = manager.get_oas(
        jschon.URI(args.initial) if args.initial else args.files[0].uri,
        '3.0',
    )
    assert entry_resource['openapi'], "First file must contain 'openapi'"

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
