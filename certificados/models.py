from django.db import models

class Event(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class CertificateTemplate(models.Model):
    MODE_CHOICES = [
        ("coords", "Escribir por coordenadas"),
        ("field", "Campo rellenable (PDF Form Field)"),
    ]

    event = models.OneToOneField(Event, on_delete=models.CASCADE)
    pdf = models.FileField(upload_to="templates/")
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default="coords")

    # Config para coords
    page_number = models.PositiveIntegerField(default=0)
    x = models.FloatField(default=100)
    y = models.FloatField(default=300)
    font_size = models.FloatField(default=28)
    align = models.CharField(max_length=10, default="center")  # left/center/right

    # Config para field
    field_name = models.CharField(max_length=100, blank=True, default="full_name")

    def __str__(self):
        return f"Template - {self.event.name}"


class DownloadLog(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    name_entered = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")

    def __str__(self):
        return f"{self.event.slug} - {self.name_entered}"