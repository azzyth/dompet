"""The Streamlit dashboard must actually *run*, not merely be served.

Regression: `streamlit run dompet/dashboard/app.py` crashed with
`ModuleNotFoundError: No module named 'dompet'`, because Streamlit puts the app's own
directory on `sys.path` instead of the repo root — the same trap as `scripts/*.py`.
`GET /_stcore/health` returned `ok` and the page returned HTTP 200 the whole time: a
dashboard whose *server* is up tells you nothing about whether its script ran, so the
guard has to execute the script itself.

`AppTest` is Streamlit's own harness for exactly this. Skips unless Streamlit and a
DATABASE_URL are available, so the stdlib suite still runs on a bare install.

Run it against the running stack with:

    docker compose exec -T dashboard python -m unittest tests.test_dashboard_app -v
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

APP_PATH = Path(__file__).resolve().parents[1] / "dompet" / "dashboard" / "app.py"

try:
    from streamlit.testing.v1 import AppTest

    HAVE_STREAMLIT = True
except ImportError:  # pragma: no cover - the stdlib suite has no streamlit
    HAVE_STREAMLIT = False

REQUIRES_DASHBOARD = unittest.skipUnless(
    HAVE_STREAMLIT and os.environ.get("DATABASE_URL"),
    "needs streamlit and a DATABASE_URL",
)


@REQUIRES_DASHBOARD
class DashboardRunsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = AppTest.from_file(str(APP_PATH), default_timeout=120).run()

    def test_no_uncaught_exception(self):
        if self.app.exception:
            self.fail(f"dashboard raised: {self.app.exception[0].value!r}")

    def test_renders_the_kpi_row(self):
        """Four metric cards — proof the layout rendered rather than bailing out."""
        self.assertGreaterEqual(
            len(self.app.metric), 4, "expected the four KPI metrics to render"
        )

    def test_renders_the_forecast_controls(self):
        self.assertGreaterEqual(len(self.app.selectbox), 1)

    def test_sidebar_reports_the_data_it_read(self):
        captions = " ".join(getattr(el, "value", "") for el in self.app.caption)
        self.assertIn("transactions", captions.lower())


if __name__ == "__main__":
    unittest.main()
