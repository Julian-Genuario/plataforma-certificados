from django.contrib import admin
from .models import Event, CertificateTemplate, DownloadLog

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "active")
    prepopulated_fields = {"slug": ("name",)}

@admin.register(CertificateTemplate)
class CertificateTemplateAdmin(admin.ModelAdmin):
    list_display = ("event", "mode", "pdf")

@admin.register(DownloadLog)
class DownloadLogAdmin(admin.ModelAdmin):
    list_display = ("event", "name_entered", "created_at")
    list_filter = ("event", "created_at")
    search_fields = ("name_entered",)