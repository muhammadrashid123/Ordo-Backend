from rest_framework.renderers import JSONRenderer


class APIRenderer(JSONRenderer):
    def render(self, data, accepted_media_type=None, renderer_context=None):
        status_code = renderer_context["response"].status_code
        if isinstance(data, dict):
            message = data.pop("message", None)
        else:
            message = None
        response = {"status": "success", "code": status_code, "data": data, "message": message}

        if not str(status_code).startswith("2"):
            response["status"] = "error"

        return super().render(response, accepted_media_type, renderer_context)
