import csv
from io import BytesIO
from datetime import timedelta

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.http import HttpResponse, StreamingHttpResponse, FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics

from .models import Event, CertificateTemplate, DownloadLog


# ── Auth ──────────────────────────────────────────────

def panel_login(request):
    if request.user.is_authenticated:
        return redirect("panel_dashboard")
    if request.method == "POST":
        username = request.POST.get("username", "")
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect("panel_dashboard")
        else:
            messages.error(request, "Usuario o contrasena incorrectos.")
    return render(request, "panel/login.html")


@login_required(login_url="panel_login")
def panel_logout_view(request):
    logout(request)
    return redirect("panel_login")


# ── Dashboard ─────────────────────────────────────────

@login_required(login_url="panel_login")
def panel_dashboard(request):
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = today_start - timedelta(days=6)

    total_events = Event.objects.count()
    active_events = Event.objects.filter(active=True).count()
    total_downloads = DownloadLog.objects.count()
    today_downloads = DownloadLog.objects.filter(created_at__gte=today_start).count()

    # Downloads per day (last 7 days)
    daily_downloads = (
        DownloadLog.objects
        .filter(created_at__gte=week_ago)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )

    # Build chart data for all 7 days
    chart_labels = []
    chart_data = []
    daily_map = {str(d["day"]): d["count"] for d in daily_downloads}
    for i in range(7):
        day = (week_ago + timedelta(days=i)).date()
        chart_labels.append(day.strftime("%d/%m"))
        chart_data.append(daily_map.get(str(day), 0))

    # Recent downloads
    recent_logs = DownloadLog.objects.select_related("event").order_by("-created_at")[:10]

    # Latest event
    latest_event = Event.objects.order_by("-id").first()

    return render(request, "panel/dashboard.html", {
        "active_page": "dashboard",
        "total_events": total_events,
        "active_events": active_events,
        "total_downloads": total_downloads,
        "today_downloads": today_downloads,
        "chart_labels": chart_labels,
        "chart_data": chart_data,
        "recent_logs": recent_logs,
        "latest_event": latest_event,
    })


# ── Events ────────────────────────────────────────────

@login_required(login_url="panel_login")
def panel_events(request):
    events = Event.objects.annotate(download_count=Count("downloadlog")).order_by("-id")
    return render(request, "panel/events.html", {
        "active_page": "events",
        "events": events,
    })


@login_required(login_url="panel_login")
def panel_event_form(request, pk=None):
    event = get_object_or_404(Event, pk=pk) if pk else None

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        slug = request.POST.get("slug", "").strip() or slugify(name)
        active = request.POST.get("active") == "on"

        if not name:
            messages.error(request, "El nombre es obligatorio.")
            return render(request, "panel/event_form.html", {
                "active_page": "events",
                "event": event,
            })

        if event:
            event.name = name
            event.slug = slug
            event.active = active
            event.save()
            messages.success(request, "Evento actualizado.")
        else:
            event = Event.objects.create(name=name, slug=slug, active=active)
            messages.success(request, "Evento creado.")

        return redirect("panel_events")

    return render(request, "panel/event_form.html", {
        "active_page": "events",
        "event": event,
    })


@login_required(login_url="panel_login")
def panel_event_toggle(request, pk):
    event = get_object_or_404(Event, pk=pk)
    event.active = not event.active
    event.save()
    state = "activado" if event.active else "desactivado"
    messages.success(request, f"Evento {state}.")
    return redirect("panel_events")


@login_required(login_url="panel_login")
def panel_event_delete(request, pk):
    event = get_object_or_404(Event, pk=pk)
    if request.method == "POST":
        event.delete()
        messages.success(request, "Evento eliminado.")
    return redirect("panel_events")


# ── Templates ─────────────────────────────────────────

@login_required(login_url="panel_login")
def panel_templates(request):
    templates = CertificateTemplate.objects.select_related("event").order_by("-id")
    events_without_template = Event.objects.exclude(
        id__in=CertificateTemplate.objects.values_list("event_id", flat=True)
    )
    return render(request, "panel/templates.html", {
        "active_page": "templates",
        "templates": templates,
        "events_without_template": events_without_template,
    })


@login_required(login_url="panel_login")
def panel_template_form(request, pk=None):
    template = get_object_or_404(CertificateTemplate, pk=pk) if pk else None

    if request.method == "POST":
        event_id = request.POST.get("event")
        mode = request.POST.get("mode", "coords")
        page_number = int(request.POST.get("page_number", 0))
        x = float(request.POST.get("x", 100))
        y = float(request.POST.get("y", 300))
        font_size = float(request.POST.get("font_size", 28))
        align = request.POST.get("align", "center")
        field_name = request.POST.get("field_name", "full_name")

        if template:
            if request.FILES.get("pdf"):
                template.pdf = request.FILES["pdf"]
            template.mode = mode
            template.page_number = page_number
            template.x = x
            template.y = y
            template.font_size = font_size
            template.align = align
            template.field_name = field_name
            template.save()
            messages.success(request, "Template actualizado.")
        else:
            if not request.FILES.get("pdf"):
                messages.error(request, "Debes subir un archivo PDF.")
                return redirect("panel_template_create")
            event = get_object_or_404(Event, pk=event_id)
            template = CertificateTemplate.objects.create(
                event=event,
                pdf=request.FILES["pdf"],
                mode=mode,
                page_number=page_number,
                x=x,
                y=y,
                font_size=font_size,
                align=align,
                field_name=field_name,
            )
            messages.success(request, "Template creado.")

        return redirect("panel_templates")

    events_available = Event.objects.exclude(
        id__in=CertificateTemplate.objects.values_list("event_id", flat=True)
    )

    return render(request, "panel/template_form.html", {
        "active_page": "templates",
        "template": template,
        "events_available": events_available,
    })


@login_required(login_url="panel_login")
def panel_template_delete(request, pk):
    template = get_object_or_404(CertificateTemplate, pk=pk)
    if request.method == "POST":
        template.delete()
        messages.success(request, "Template eliminado.")
    return redirect("panel_templates")


@login_required(login_url="panel_login")
def panel_template_preview(request, pk):
    """Generate a preview PDF with a sample name and return as image-like PDF."""
    template = get_object_or_404(CertificateTemplate, pk=pk)
    sample_name = request.GET.get("name", "Juan Perez")

    reader = PdfReader(template.pdf.path)
    writer = PdfWriter()

    page_index = template.page_number
    if page_index >= len(reader.pages):
        return HttpResponse("Pagina invalida", status=400)

    for i, page in enumerate(reader.pages):
        if i == page_index:
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)

            packet = BytesIO()
            c = canvas.Canvas(packet, pagesize=(width, height))
            font_name = "Helvetica"
            font_size = float(template.font_size)
            c.setFont(font_name, font_size)

            x = float(template.x)
            y = float(template.y)
            align = (template.align or "center").lower()
            text_width = pdfmetrics.stringWidth(sample_name, font_name, font_size)

            if align == "center":
                draw_x = x - (text_width / 2.0)
            elif align == "right":
                draw_x = x - text_width
            else:
                draw_x = x

            c.drawString(draw_x, y, sample_name)
            c.save()

            packet.seek(0)
            overlay_pdf = PdfReader(packet)
            page.merge_page(overlay_pdf.pages[0])

        writer.add_page(page)

    out = BytesIO()
    writer.write(out)
    out.seek(0)

    return FileResponse(out, content_type="application/pdf", filename="preview.pdf")


# ── Logs ──────────────────────────────────────────────

@login_required(login_url="panel_login")
def panel_logs(request):
    logs = DownloadLog.objects.select_related("event").order_by("-created_at")

    # Filters
    event_filter = request.GET.get("event")
    search = request.GET.get("search", "").strip()
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")

    if event_filter:
        logs = logs.filter(event_id=event_filter)
    if search:
        logs = logs.filter(name_entered__icontains=search)
    if date_from:
        logs = logs.filter(created_at__date__gte=date_from)
    if date_to:
        logs = logs.filter(created_at__date__lte=date_to)

    events = Event.objects.order_by("name")

    # Simple pagination
    page = int(request.GET.get("page", 1))
    per_page = 25
    total = logs.count()
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    logs_page = logs[(page - 1) * per_page : page * per_page]

    return render(request, "panel/logs.html", {
        "active_page": "logs",
        "logs": logs_page,
        "events": events,
        "event_filter": event_filter,
        "search": search,
        "date_from": date_from or "",
        "date_to": date_to or "",
        "page": page,
        "total_pages": total_pages,
        "total": total,
    })


@login_required(login_url="panel_login")
def panel_logs_export(request):
    logs = DownloadLog.objects.select_related("event").order_by("-created_at")

    event_filter = request.GET.get("event")
    search = request.GET.get("search", "").strip()
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")

    if event_filter:
        logs = logs.filter(event_id=event_filter)
    if search:
        logs = logs.filter(name_entered__icontains=search)
    if date_from:
        logs = logs.filter(created_at__date__gte=date_from)
    if date_to:
        logs = logs.filter(created_at__date__lte=date_to)

    def generate():
        writer = csv.writer(row_buffer := BytesIO(), dialect="excel")
        # Header
        writer.writerow(["Evento", "Nombre", "Fecha", "IP", "User Agent"])
        yield row_buffer.getvalue().decode("utf-8")
        row_buffer.seek(0)
        row_buffer.truncate()

        for log in logs.iterator():
            writer.writerow([
                log.event.name,
                log.name_entered,
                log.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                log.ip or "",
                log.user_agent,
            ])
            yield row_buffer.getvalue().decode("utf-8")
            row_buffer.seek(0)
            row_buffer.truncate()

    response = StreamingHttpResponse(generate(), content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="descargas.csv"'
    return response


# ── Users ─────────────────────────────────────────────

@login_required(login_url="panel_login")
def panel_users(request):
    users = User.objects.filter(is_staff=True).order_by("-date_joined")
    return render(request, "panel/users.html", {
        "active_page": "users",
        "users": users,
    })


@login_required(login_url="panel_login")
def panel_user_form(request, pk=None):
    user_obj = get_object_or_404(User, pk=pk) if pk else None

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "").strip()
        is_superuser = request.POST.get("is_superuser") == "on"

        if not username:
            messages.error(request, "El usuario es obligatorio.")
            return render(request, "panel/user_form.html", {
                "active_page": "users",
                "user_obj": user_obj,
            })

        if user_obj:
            user_obj.username = username
            user_obj.email = email
            user_obj.is_superuser = is_superuser
            if password:
                user_obj.set_password(password)
            user_obj.save()
            messages.success(request, "Usuario actualizado.")
        else:
            if not password:
                messages.error(request, "La contrasena es obligatoria para nuevos usuarios.")
                return render(request, "panel/user_form.html", {
                    "active_page": "users",
                    "user_obj": user_obj,
                })
            if User.objects.filter(username=username).exists():
                messages.error(request, "Ese nombre de usuario ya existe.")
                return render(request, "panel/user_form.html", {
                    "active_page": "users",
                    "user_obj": user_obj,
                })
            user_obj = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                is_staff=True,
                is_superuser=is_superuser,
            )
            messages.success(request, "Usuario creado.")

        return redirect("panel_users")

    return render(request, "panel/user_form.html", {
        "active_page": "users",
        "user_obj": user_obj,
    })


@login_required(login_url="panel_login")
def panel_user_delete(request, pk):
    user_obj = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        if user_obj == request.user:
            messages.error(request, "No podes eliminar tu propio usuario.")
        else:
            user_obj.delete()
            messages.success(request, "Usuario eliminado.")
    return redirect("panel_users")
