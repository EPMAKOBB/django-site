import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.template import Context, Template
from django.test import SimpleTestCase

from accounts.templatetags.versioned_assets import versioned_static


class VersionedAssetsTests(SimpleTestCase):
    def test_asset_url_changes_when_contents_change_at_the_same_path(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "training-builder.js"
            source.write_text("old client", encoding="utf-8")
            with patch("accounts.templatetags.versioned_assets.finders.find", return_value=str(source)):
                first = versioned_static("js/training-builder.js")
                modified = source.stat().st_mtime_ns
                source.write_text("new client", encoding="utf-8")
                os.utime(source, ns=(modified + 1000000, modified + 1000000))
                second = versioned_static("js/training-builder.js")
            self.assertNotEqual(first, second)
            self.assertIn("?v=", second)

    def test_training_templates_use_content_versions_for_scripts_and_styles(self):
        paths = ["js/training-builder.js", "js/training-solver.js", "css/training-builder.css", "css/solver.css"]
        for path in paths:
            rendered = Template("{% load versioned_assets %}{% versioned_static path %}").render(Context({"path": path}))
            self.assertIn("?v=", rendered)
            self.assertNotIn("stable-load-20261025", rendered)
