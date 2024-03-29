import base64
import io
import uuid

import six
from django.core.files.base import ContentFile
from django.core.validators import URLValidator
from PIL import Image
from rest_framework.serializers import ImageField, ValidationError


class Base64ImageField(ImageField):
    def to_internal_value(self, data):
        if isinstance(data, six.string_types) and data.startswith("data:image"):
            header, data = data.split(";base64,")

            try:
                decoded_file = base64.b64decode(data)
            except TypeError:
                self.fail("invalid_image")

            file_name = str(uuid.uuid4())[:12]
            file_extension = self.get_file_extension(file_name, decoded_file)
            complete_file_name = "%s.%s" % (
                file_name,
                file_extension,
            )
            data = ContentFile(decoded_file, name=complete_file_name)

        return super(Base64ImageField, self).to_internal_value(data)

    def get_file_extension(self, file_name, decoded_file):
        image = Image.open(io.BytesIO(decoded_file))
        extension = image.format.lower()
        extension = "jpg" if extension == "jpeg" else extension

        return extension


class PhoneNumberValidator:
    def __call__(self, phone_number):
        if not phone_number.isdigit():
            raise ValidationError("Only digits are allowed")


class OptionalSchemeURLValidator(URLValidator):
    def __call__(self, value):
        if "://" not in value:
            value = f"https://{value}"
        super(OptionalSchemeURLValidator, self).__call__(value)
