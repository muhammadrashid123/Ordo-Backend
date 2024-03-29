from flashtext import KeywordProcessor

from apps.common.singleton import Singleton

SUBSTITUTIONS = [
    ("legacy 3", "legacy3"),
]


class Replacer(metaclass=Singleton):
    def __init__(self):
        self.processor = KeywordProcessor()
        for src, dst in SUBSTITUTIONS:
            self.processor.add_keyword(src, dst)

    def replace(self, src):
        return self.processor.replace_keywords(src)
