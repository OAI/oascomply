import sys
import argparse
import json
import subprocess
from collections import OrderedDict
from io import StringIO
from pathlib import Path

import yaml
import json_merge_patch
from jschon.jsonpatch import JSONPatch

PATCH_SCHEMAS_DESCRIPTION = """
Load the standard OAS 3.x schemas from submodules/OpenAPI-Specification,
migrate older schemas to 2020-12 using alterschema, apply the appropriate
patches from patches/oas/..., and write the patched schemas to schemas/oas/...
with the same tree structure as in OpenAPI-Specification/schemas.  These
patched schemas should be checked in, matching the current state of the
submodule.  See CONTRIBUTING.md for more detail on when and how to update.

Note that currently only OAS v3.0 is supported.
"""

YAML_TO_JASON_DESCRIPTION = """
Convert a YAML file to a JSON file, as JSON is much faster to process.

Note that error handling is minimal, and output files are overwritten
if present.
"""

def yaml_to_json():
    parser = argparse.ArgumentParser(
        description=YAML_TO_JASON_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        'infile',
        nargs='+',
        help='YAML files to convert'
    )
    parser.add_argument(
        '-o',
        '--outfile',
    )
    parser.add_argument(
        '-n',
        '--indent',
        type=int,
        default=2,
        help='Indentation level: 0 for newlines without indenting, '
             '-1 for no whitespace of any kind',
    )
    args = parser.parse_args()

    infiles = [Path(i) for i in args.infile]
    if len(infiles) > 1 and args.outfile:
        sys.stderr.write(
            'Cannot specify --output-file with multiple input files\n'
        )
        sys.exit(-1)
    elif args.outfile:
        outfiles = [Path(args.outfile)]
    else:
        outfiles = [i.with_suffix('.json') for i in infiles]

    kwargs = {
        'ensure_ascii': False,
        'indent': args.indent if args.indent >=0 else None,
    }
    if args.indent < 0:
        kwargs['separators'] = (',', ':')

    for index, infile in enumerate(infiles):
        with infile.open() as in_fp, outfiles[index].open(
            'w', encoding='utf-8'
        ) as out_fp:
            json.dump(yaml.safe_load(in_fp), out_fp, **kwargs)


def patch():
    argparse.ArgumentParser(
        description=PATCH_SCHEMAS_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    ).parse_args()

    repo_root = (Path(__file__).parent / '..' ).resolve() 
    oas_schema_dir = (
        repo_root / 'submodules' / 'OpenAPI-Specification' / 'schemas'
    )
    oas_v30_schema = oas_schema_dir / 'v3.0' / 'schema.json'

    print(
        f'Running alterschema (draft4 to 2020-12) on "{oas_v30_schema}", '
        'this may take a while...'
    )
    result = subprocess.run(
        [
            'alterschema',
            '--from',
            'draft4',
            '--to',
            '2020-12',
            str(oas_v30_schema),
        ],
        capture_output=True,
        encoding='utf-8',
        check=True,
    )

    # OrderedDict.move_to_end(..., last=False) moves to beginning.
    # Since "id" gets changed to "$id" it gets moved later in the dict.
    # "$defs" should be the last root-level keyword, so it getting
    # changed from "definitions" leaves it in the right place.
    schema = json.loads(result.stdout, object_hook=OrderedDict)
    schema.move_to_end('$id', last=False)

    oas_patch_dir = repo_root / 'patches' / 'oas'
    prelim_patch = oas_patch_dir / 'v3.0' / 'preliminary-patch.json'
    print(f'Applying JSON Patch (RFC 6902) "{prelim_patch}" ...')
    with open(prelim_patch, encoding='utf-8') as prelim_fp:
        prelim = json.load(prelim_fp)
    patched = JSONPatch(*prelim).evaluate(schema)

    merge_patch = oas_patch_dir / 'v3.0' / 'merge-patch.yaml'
    print(f'Applying JSON Merge Patch (RFC 7396) "{merge_patch}" ...')
    with open(merge_patch, encoding='utf-8') as merge_fp:
        merge = yaml.safe_load(merge_fp)
    json_merge_patch.merge(patched, merge)

    # move $defs to the end after patching in more root-level keywords.
    # Don't bother constructing an OrderedDict for this as supported
    # versions of python preserve insert order.
    defs = patched['$defs']
    del patched['$defs']
    patched['$defs'] = defs

    patched_file = repo_root / 'schemas' / 'oas' / 'v3.0' / 'schema.json'
    print(f'Writing patched schema to "{patched_file}" ...')
    with open(patched_file, 'w', encoding='utf-8') as patched_fp:
        # For some reason there is no option for json.dump() to
        # include a trailing newline.
        json.dump(patched, patched_fp, indent=2, allow_nan=False)
        patched_fp.write('\n')
    print("Done!")
    print()
