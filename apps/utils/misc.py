import decimal


def normalize_decimal_values(d: dict):
    result = {}
    for k, v in d.items():
        if isinstance(v, decimal.Decimal):
            result[k] = str(v)
        elif isinstance(v, list):
            result[k] = [normalize_decimal_values(o) for o in v]
        elif isinstance(v, dict):
            result[k] = normalize_decimal_values(v)
        else:
            result[k] = v
    return result
