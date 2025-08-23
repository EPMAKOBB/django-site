from django.shortcuts import render


def home(request):
    """Render the main landing page."""
    return render(request, "home.html")

