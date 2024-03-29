from lxml import etree


def dict2xml(obj, element_name: str = "root") -> etree.Element:
    root = etree.Element(element_name)

    def _dict2xml(parent, dict_obj):
        for key, value in dict_obj.items():
            if key.startswith("@"):
                if ":" in key:
                    prefix, attr = key[1:].split(":")
                    if prefix == "xml" and attr == "lang":
                        parent.set("{http://www.w3.org/XML/1998/namespace}lang", value)
                else:
                    parent.set(key[1:], str(value))

            elif key == "#text":
                parent.text = str(value)
            elif isinstance(value, dict):
                child = etree.SubElement(parent, key)
                _dict2xml(child, value)
            elif isinstance(value, list):
                for item in value:
                    child = etree.SubElement(parent, key)
                    if isinstance(item, dict):
                        _dict2xml(child, item)
                    else:
                        child.text = str(item)
            else:
                child = etree.SubElement(parent, key)
                child.text = str(value)

    _dict2xml(root, obj)
    return root
