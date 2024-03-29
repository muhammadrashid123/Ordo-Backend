import datetime

from colorfield.fields import ColorField
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def validate_future_date(value):
    if value < timezone.now().date():
        raise ValidationError("Date cannot be in the past.")


class Role(models.IntegerChoices):
    all = 0
    admin = 1
    sub_admin = 3
    user = 2


BACKGROUND_COLOR_PALETTE = [
    ("#ff1dc3", "pink"),
    ("#FF0000", "red"),
    ("#00FF00", "green"),
    ("#0000FF", "blue"),
]

FOREGROUND_COLOR_PALETTE = [
    ("#ffffff", "white"),
    ("#000000", "black"),
    ("#FF0000", "red"),
    ("#00FF00", "green"),
]


def after_seven_days():
    return datetime.date.today() + datetime.timedelta(days=7)


class Greetings(models.Model):
    title = models.CharField(max_length=128)
    sub_title = models.CharField(max_length=512, null=True, blank=True)
    start_date = models.DateField(default=datetime.date.today)
    end_date = models.DateField(default=after_seven_days)
    users = models.IntegerField(choices=Role.choices, default=Role.all)
    once = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    background_color = ColorField(default="#ff1dc3", samples=BACKGROUND_COLOR_PALETTE)
    foreground_color = ColorField(default="#ffffff", samples=FOREGROUND_COLOR_PALETTE)

    def __str__(self):
        return self.title

    class Meta:
        verbose_name_plural = "Greetings"
