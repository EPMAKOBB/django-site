from django.http import FileResponse, Http404, HttpResponse, StreamingHttpResponse
from django.views.generic import TemplateView
from django.core.files.storage import default_storage
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from applications.forms import ApplicationForm
from applications.utils import get_application_price
from apps.recsys.models import ExamVersion


class HomeView(TemplateView):
    """Render the main landing page."""
    template_name = "home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = ApplicationForm(self.request.GET or None)
        context["form"] = form

        subjects_count = 0
        data = form.data if form.is_bound else form.initial
        if data.get("subject1"):
            subjects_count += 1
        if data.get("subject2"):
            subjects_count += 1

        context["subjects_count"] = subjects_count
        context["application_price"] = get_application_price(subjects_count)
        context["active_exams"] = (
            ExamVersion.objects.filter(status=ExamVersion.Status.ACTIVE)
            .select_related("subject")
            .order_by("subject__name", "name")
        )
        return context


class KrylovView(TemplateView):
    """Render the Krylov downloads page."""
    template_name = "krylov.html"


def krylov_download(request, kind):
    files = {
        "pdf": {
            "path": "tasks/inf/files/Krylov_2026.pdf",
            "filename": "Krylov_2026.pdf",
            "content_type": "application/pdf",
            "remote_url": "https://www.fractalschool.ru/media/tasks/inf/files/Krylov_2026.pdf",
        },
        "rar": {
            "path": "tasks/inf/files/krylov_files.rar",
            "filename": "Krylov_files.rar",
            "content_type": "application/vnd.rar",
            "remote_url": "https://www.fractalschool.ru/media/tasks/inf/files/krylov_files.rar",
        },
    }

    file_meta = files.get(kind)
    if not file_meta:
        raise Http404("File not found")

    try:
        file_handle = default_storage.open(file_meta["path"], "rb")
    except FileNotFoundError:
        file_handle = None

    if file_handle is not None:
        return FileResponse(
            file_handle,
            as_attachment=True,
            filename=file_meta["filename"],
            content_type=file_meta["content_type"],
        )

    # Fallback: stream from remote URL but force attachment for the browser.
    try:
        remote_request = Request(file_meta["remote_url"], headers={"User-Agent": "FractalSchool"})
        remote_response = urlopen(remote_request, timeout=20)
    except (HTTPError, URLError) as exc:
        raise Http404("File not found") from exc

    def stream_chunks(response, chunk_size=8192):
        while True:
            chunk = response.read(chunk_size)
            if not chunk:
                break
            yield chunk

    response = StreamingHttpResponse(
        stream_chunks(remote_response),
        content_type=file_meta["content_type"],
    )
    response["Content-Disposition"] = f'attachment; filename="{file_meta["filename"]}"'
    content_length = remote_response.headers.get("Content-Length")
    if content_length:
        response["Content-Length"] = content_length
    return response


def robots_txt(request):
    sitemap_url = f"{request.scheme}://{request.get_host()}/sitemap.xml"
    lines = [
        "User-agent: *",
        "Disallow: /admin/",
        "Disallow: /accounts/",
        "Disallow: /tasks/",
        "Disallow: /recsys/",
        "Disallow: /parser/",
        "Disallow: /api/",
        "Allow: /",
        f"Sitemap: {sitemap_url}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")
