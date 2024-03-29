import logging

from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.status import HTTP_400_BAD_REQUEST
from rest_framework.views import APIView

from apps.accounts import models as m
from apps.common import messages as msgs
from apps.common.enums import OnboardingStep

logger = logging.getLogger(__name__)


class CompanyMemberInvitationCheckAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, token):
        invite = m.CompanyMember.objects.filter(token=token).first()
        if invite is None:
            return Response({"message": msgs.INVITE_TOKEN_WRONG}, status=HTTP_400_BAD_REQUEST)

        company = invite.company

        # LINK_VENDOR is the minimum last step.
        if company.on_boarding_step < OnboardingStep.LINK_VENDOR:
            return Response({"message": msgs.INVITE_NOT_ACCEPTABLE}, status=HTTP_400_BAD_REQUEST)

        now = timezone.localtime()
        if invite.token_expires_at < now:
            return Response({"message": msgs.INVITE_TOKEN_EXPIRED}, status=HTTP_400_BAD_REQUEST)

        if invite.user:
            invite.invite_status = m.CompanyMember.InviteStatus.INVITE_APPROVED
            invite.date_joined = timezone.localtime()
            invite.save()
            # Removing all scheduled unsent invites
            m.CompanyMemberInviteSchedule.cancel_for_member(company_member_id=invite.pk)
            return Response({"redirect": "login"})

        return Response(
            {
                "redirect": "signup",
                "email": invite.email,
                "company": invite.company.name,
                "role": invite.role,
                "token": token,
            }
        )
