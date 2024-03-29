from django.contrib.auth import get_user_model
from rest_framework import authentication, exceptions
from rest_framework.authentication import get_authorization_header


class PseudoEmailAuthentication(authentication.BaseAuthentication):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_model = get_user_model()

    def authenticate(self, request):
        auth = get_authorization_header(request).split()

        if not auth or auth[0].lower() != b"email":
            return None

        if len(auth) == 1:
            msg = "Invalid email header. No credentials provided."
            raise exceptions.AuthenticationFailed(msg)
        elif len(auth) > 2:
            msg = "Invalid basic header. Credentials string should not contain spaces."
            raise exceptions.AuthenticationFailed(msg)

        email = auth[1].decode()
        try:
            user = self.user_model.objects.get(email=email)
        except self.user_model.DoesNotExist:
            msg = "User not found"
            raise exceptions.AuthenticationFailed(msg)
        return (user, None)
