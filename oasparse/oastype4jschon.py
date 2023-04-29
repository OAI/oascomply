from jschon.vocabulary import Keyword


class _AnnotationKeyword(Keyword):
    def evaluate(self, instance, result):
        result.annotate(self.json.data)
        result.noassert()


class OasType(_AnnotationKeyword):
    key = 'oasType'


class OasSubType(_AnnotationKeyword):
    key = 'oasSubType'

