from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Greetings
from .serializers import GreetingsSerializer


class GetLastGreetings(APIView):
    def get(self, request):
        try:
            last_greeting = Greetings.objects.last()

            if last_greeting:
                serializer = GreetingsSerializer(last_greeting)
                return Response(serializer.data, status=status.HTTP_200_OK)
            else:
                return Response({"detail": "No greetings found"}, status=status.HTTP_404_NOT_FOUND)

        except ObjectDoesNotExist:
            return Response({"detail": "Greetings not found"}, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class GetAllGreetings(APIView):
    def get(self, request):
        try:
            greetings = Greetings.objects.all()
            serializer = GreetingsSerializer(greetings, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except ObjectDoesNotExist:
            return Response({"detail": "No greetings found"}, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class GetGreetingsByRole(APIView):
    def get(self, request, role):
        today = timezone.now().date()

        try:
            greetings = Greetings.objects.filter(
                Q(start_date__lte=today) & Q(end_date__gte=today), Q(users=0) | Q(users=role), active=True
            )
            serializer = GreetingsSerializer(greetings, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except ObjectDoesNotExist:
            return Response({"detail": "No greetings found"}, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
