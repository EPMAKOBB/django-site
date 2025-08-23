from django.http import HttpResponse


def home(request):
    """Render a simple greeting on the home page."""
    return HttpResponse("привет мир!")

