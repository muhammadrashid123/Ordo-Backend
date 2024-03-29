from django.db import models


class WaitList(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    practice_name = models.CharField(max_length=200)
    email = models.EmailField(max_length=254, unique=True)
    join_date = models.DateField(auto_now_add=True)
    # provided_coupen = models.BooleanField(default=False)
    note = models.CharField(max_length=300, null=True, blank=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name} "

    class Meta:
        verbose_name_plural = "Wait Lists"
