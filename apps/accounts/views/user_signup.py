from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.status import HTTP_400_BAD_REQUEST
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts import models as m
from apps.accounts import serializers as s
from apps.common import messages as msgs
from apps.common.enums import OnboardingStep


class UserSignupAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = s.UserSignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            if m.User.objects.filter(email=serializer.validated_data["email"]).exists():
                return Response({"message": msgs.SIGNUP_DUPLICATE_EMAIL}, status=HTTP_400_BAD_REQUEST)

            company_name = serializer.validated_data.pop("company_name", None)
            token = serializer.validated_data.pop("token", None)
            user = m.User.objects.create_user(
                username=serializer.validated_data["email"],
                **serializer.validated_data,
            )
            if token:
                company_member = m.CompanyMember.objects.filter(
                    token=token, email=serializer.validated_data["email"]
                ).first()
                if not company_member:
                    raise ValidationError("Your invite not found")
                company_member.user = user
                company_member.invite_status = m.CompanyMember.InviteStatus.INVITE_APPROVED
                company_member.date_joined = timezone.localtime()
                company_member.save()
                # update the user role with the company member role to be matched...
                user.role = company_member.role
                user.save()

                company = company_member.company
            else:
                company = m.Company.objects.create(
                    name=company_name, on_boarding_step=OnboardingStep.ACCOUNT_SETUP, creator=user
                )
                company_member = m.CompanyMember.objects.create(
                    company=company,
                    user=user,
                    role=m.User.Role.ADMIN,
                    office=None,
                    email=user.email,
                    invite_status=m.CompanyMember.InviteStatus.INVITE_APPROVED,
                    date_joined=timezone.localtime(),
                )
            m.CompanyMemberInviteSchedule.cancel_for_member(company_member_id=company_member.pk)

        token = RefreshToken.for_user(user).access_token
        token["username"] = user.username
        token["email"] = user.username
        return Response(
            {
                "token": str(token),
                "company": s.CompanySerializer(company).data,
            }
        )
