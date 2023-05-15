from typing import Generator, Sequence, Tuple, Union
from collections import namedtuple
import re
import jschon

TEMPLATE_UNESCAPED = r'[\x00-.0-z|\x7f-\U0010ffff]'
TEMPLATE_VARIABLE = f'{TEMPLATE_UNESCAPED}*'
TEMPLATE_TOKEN = r'\{(' + TEMPLATE_VARIABLE + r')\}'
TEMPLATE_ESCAPED = r'\~[0123]'
NON_TEMPLATE_TOKEN = f'(?:{TEMPLATE_UNESCAPED}|{TEMPLATE_ESCAPED})*'
BASIC_POINTER_TEMPLATE = f'(?:/(?:{TEMPLATE_TOKEN}|{NON_TEMPLATE_TOKEN}))*'
JSON_POINTER_TEMPLATE = f'{BASIC_POINTER_TEMPLATE}(?:{TEMPLATE_TOKEN}#)?'


TemplateResult = namedtuple(
    'TemplateResult',
    ['pointer', 'data', 'variables', 'index'],
)


class GenericPointerTemplateError(Exception):
    pass


class JSONPointerTemplateError(GenericPointerTemplateError):
    pass


class InvalidJSONPointerTemplateError(JSONPointerTemplateError):
    pass


class JSONPointerTemplateEvaluationError(JSONPointerTemplateError):
    pass


class JSONPointerTemplate:
    def __init__(self, template: str):
        if (m := re.fullmatch(JSON_POINTER_TEMPLATE, template)) is None:
            raise InvalidJSONPointerTemplateError(
                f'{template!r} is not a valid JSONPointerTemplate!'
            )
        self._template = template

        # Splitting '' results in [''], and '/' in ['', ''],
        # so always remove the initial ''
        segments = template.split('/')[1:]

        # Components are one of:
        # * JSONPointer instances
        # * A template variable name (str instance)
        # * Boolean True to request the name of the key or number
        #   of the index matching the previous variable; this can
        #   only occur as the last component
        self._components= []
        currptr = jschon.JSONPointer()
        for s in segments:
            if s.startswith('{'):
                if len(currptr) > 0:
                    self._components.append(currptr)
                    currptr = jschon.JSONPointer()
                if s.endswith('#'):
                    self._components.extend((s[1:-2], True))
                else:
                    self._components.append(s[1:-1])
            else:
                currptr /= self.unescape(s)

        if len(currptr) or not len(self._components):
            self._components.append(currptr)

    def __str__(self):
        return self._template

    def __eq__(self, other):
        return (
            isinstance(other, type(self)) and
            self._template == other._template
        )

    def evaluate(
        self,
        instance: jschon.JSON,
        *,
        require_match: bool = False,
        _index=0,
        _resolved=jschon.JSONPointer(),
        _variables=None,
        _previous_variable=None,
    ) -> Generator[
        Tuple[
            jschon.JSONPointer,
            jschon.JSON,
            Union[None, str, int],
        ],
        None,
        None,
    ]:
        remaining = self._components[_index:]
        variables = _variables or {}

        if len(remaining) == 0:
            yield TemplateResult(_resolved, instance, variables, None)
            return

        next_c = remaining[0]
        if isinstance(next_c, jschon.JSONPointer):
            new_resolved = _resolved / next_c
            try:
                new_instance = next_c.evaluate(instance)
            except jschon.JSONPointerError as e:
                if not require_match:
                    return
                raise JSONPointerTemplateEvaluationError(
                    f"Path '{new_resolved}' not found in document {instance} while "
                    f"evaluating template '{self}'"
                ) from e

            yield from self.evaluate(
                new_instance,
                require_match=require_match,
                _index=_index + 1,
                _resolved=new_resolved,
                _variables=variables,
            )

        elif isinstance(next_c, str):
            if instance.type == 'array':
                keys = range(len(instance))
            elif instance.type == 'object':
                keys = instance.keys()
            else:
                raise JSONPointerTemplateEvaluationError(
                    f"Cannot match template variable {next_c!r} from "
                    f"template '{self}' – instance locattion '{_resolved}' "
                    f"is a {instance.type!r}, not an array or object."
                )

            for key in keys:
                newvars = variables.copy()
                newvars[next_c] = key
                yield from (
                    self.evaluate(
                        instance[key],
                        require_match=require_match,
                        _index=_index + 1,
                        _resolved=_resolved / str(key),
                        _variables=newvars,
                    )
                )
        else:
            assert next_c is True
            prev_val = next(reversed(variables.values()))
            yield TemplateResult(_resolved, instance, variables, prev_val)


    @staticmethod
    def escape(component):
        return (
            component
                .replace('~', '~0')
                .replace('/', '~1')
                .replace('{', '~2')
                .replace('}', '~3')
        )

    @staticmethod
    def unescape(component):
        return (
            component
                .replace('~3', '}')
                .replace('~2', '{')
                .replace('~1', '/')
                .replace('~0', '~')
        )


class RelativeJSONPointerTemplateError(GenericPointerTemplateError):
    pass


class InvalidRelativeJSONPointerTemplateError(
    RelativeJSONPointerTemplateError
):
    pass


class RelativeJSONPointerTemplateEvaluationError(
    RelativeJSONPointerTemplateError
):
    pass


class RelativeJSONPointerTemplate:
    def __init__(self, template: str):
        try:
            try:
                slash = template.index('/')
                if template[slash -1] == '#':
                    raise InvalidRelativeJSONPointerTemplateError(
                        "Can't use '#' in origin adjustment with template path"
                    )
                self._relptr = jschon.RelativeJSONPointer(template[:slash])
                self._jptemplate = JSONPointerTemplate(template[slash:])
            except ValueError:
                self._relptr = jschon.RelativeJSONPointer(template)
                self._jptemplate = None
        except (
            jschon.JSONPointerError,
            jschon.RelativeJSONPointerError,
            InvalidJSONPointerTemplateError,
        ) as e:
            raise InvalidRelativeJSONPointerTemplateError(
                f"{template!r} is not a valid RelativeJSONPointerTemplate!",
            ) from e
        self._template = template

    def __str__(self):
        return self._template

    def __eq__(self, other):
        return (
            isinstance(other, type(self)) and
            self._template == other._template
        )

    def evaluate(self, instance, *, require_match=False):
        try:
            base = self._relptr.evaluate(instance)
        except jschon.RelativeJSONPointerError as e:
            raise RelativeJSONPointerTemplateEvaluationError(
                f"Could not evaluate origin adjustment of {self._template}",
            ) from e

        if self._jptemplate is None:
            if self._relptr.index:
                # Since we already evaluated the full relptr,
                # we know this will not raise an exception
                value = jschon.RelativeJSONPointer(
                    self._template[:-1]
                ).evaluate(instance)
                name = base
            else:
                value = base
                name = None
            yield TemplateResult(self._relptr, value, {}, name)
            return

        try:
            yield from (
                TemplateResult(
                    jschon.RelativeJSONPointer(
                        up=self._relptr.up,
                        over=self._relptr.over,
                        ref=result[0],
                    ),
                    result.data,
                    result.variables,
                    result.index,
                )
                for result in self._jptemplate.evaluate(
                    base,
                    require_match=require_match,
                )
            )
        except JSONPointerTemplateError as e:
            raise RelativeJSONPointerTemplateEvaluationError(
                e.args[0] +
                f" (after applying relative pointer '{self._relptr}')",
            ) from e
