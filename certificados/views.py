from io import BytesIO

from django.http import FileResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics

from .models import Event, CertificateTemplate, DownloadLog


def _get_client_ip(request):
    return request.META.get("REMOTE_ADDR")


def event_page(request, slug):
    event = get_object_or_404(Event, slug=slug, active=True)
    return render(request, "certificados/event_page.html", {"event": event})


def download_certificate(request, slug):
    if request.method != "POST":
        return HttpResponseBadRequest("Método no permitido.")

    event = get_object_or_404(Event, slug=slug, active=True)
    template = get_object_or_404(CertificateTemplate, event=event)

    full_name = (request.POST.get("full_name") or "").strip()
    if not full_name:
        return HttpResponseBadRequest("Nombre vacío.")
    if len(full_name) > 80:
        return HttpResponseBadRequest("Nombre demasiado largo (máx 80).")

    # Log de descarga
    DownloadLog.objects.create(
        event=event,
        name_entered=full_name,
        ip=_get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )

    # Leer el PDF template
    reader = PdfReader(template.pdf.path)
    writer = PdfWriter()

    page_index = template.page_number
    if page_index >= len(reader.pages):
        return HttpResponseBadRequest("page_number inválido para este PDF.")

    # Copiamos todas las páginas y en la página objetivo superponemos el texto
    for i, page in enumerate(reader.pages):
        if i == page_index:
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)

            # Overlay con reportlab
            packet = BytesIO()
            c = canvas.Canvas(packet, pagesize=(width, height))

            font_name = "Helvetica"
            font_size = float(template.font_size)
            c.setFont(font_name, font_size)

            x = float(template.x)
            y = float(template.y)

            align = (template.align or "center").lower()
            text_width = pdfmetrics.stringWidth(full_name, font_name, font_size)

            if align == "center":
                draw_x = x - (text_width / 2.0)
            elif align == "right":
                draw_x = x - text_width
            else:
                draw_x = x

            c.drawString(draw_x, y, full_name)
            c.save()

            packet.seek(0)
            overlay_pdf = PdfReader(packet)
            overlay_page = overlay_pdf.pages[0]

            page.merge_page(overlay_page)

        writer.add_page(page)

    out = BytesIO()
    writer.write(out)
    out.seek(0)

    filename = f"certificado-{event.slug}.pdf"
    return FileResponse(out, as_attachment=True, filename=filename)