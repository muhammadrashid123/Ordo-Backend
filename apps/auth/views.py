from django.contrib.auth.models import update_last_login
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenVerifySerializer,
)
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import UntypedToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenVerifyView

from apps.accounts.models import User
from apps.accounts.serializers import UserSerializer

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import IsAuthenticated
from apps.accounts.permissions import IsSuperUser

class MyTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        refresh = self.get_token(self.user)
        data["token"] = str(refresh.access_token)
        data.pop("access")
        data.pop("refresh")
        if api_settings.UPDATE_LAST_LOGIN:
            update_last_login(None, self.user)
        data["profile"] = UserSerializer(instance=self.user, context=self.context).data
        return data

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["username"] = user.username
        token["email"] = user.username
        return token

    @classmethod
    def get_token_for_impersonation(cls, user):
        refresh = RefreshToken.for_user(user)

        refresh['username'] = user.username

        return refresh

class MyTokenVerifySerializer(TokenVerifySerializer):
    def validate(self, attrs):
        token = UntypedToken(attrs["token"])
        user = User.objects.get(username=token.payload["username"])
        return {"token": attrs["token"], "profile": UserSerializer(instance=user, context=self.context).data}


class MyTokenObtainPairView(TokenObtainPairView):
    serializer_class = MyTokenObtainPairSerializer


class MyTokenVerifyView(TokenVerifyView):
    serializer_class = MyTokenVerifySerializer

class ImpersonateUser(APIView):
    permission_classes = [IsAuthenticated, IsSuperUser]

    def post(self, request, user_id, *args, **kwargs):
        try:
            user_to_impersonate = User.objects.get(id=user_id)

            # Generate token for impersonation
            refresh = MyTokenObtainPairSerializer.get_token_for_impersonation(user_to_impersonate)
            data = {'refresh': str(refresh), 'access': str(refresh.access_token)}

            data["token"] = str(refresh.access_token)
            data.pop("access")
            data.pop("refresh")

            data["profile"] = UserSerializer(instance=user_to_impersonate).data

            return Response(data)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=404)
