from urllib.parse import quote


def get_content_disposition_header(filename):
    try:
        filename.encode('ascii')
        file_expr = 'filename="{}"'.format(filename)
    except UnicodeEncodeError:
        file_expr = "filename*=utf-8''{}".format(quote(filename))
    return f"attachment; {file_expr}"