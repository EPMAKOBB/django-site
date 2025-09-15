import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fractalschool.settings")
import django
django.setup()

from applications.forms import ApplicationForm

data = {
    "grade": 11,
    "subject1": 1,
    "subject2": "",
    "contact_info": "Тестовая заявка",
    "contact_name": "Тестер",
    "source_offer": "",
}

form = ApplicationForm(data=data)
print("is_valid:", form.is_valid())
print("errors:", form.errors)
if form.is_valid():
    app = form.save()
    print("saved application id:", app.id)
    print("subjects:", list(app.subjects.values_list("id", flat=True)))
