from rest_framework.parsers import BaseParser


class XMLParser(BaseParser):
    media_type = "application/xml"

    def parse(self, stream, media_type=None, parser_context=None):
        return stream.read().decode("utf-8")
