"""dompet — a personal finance tracker that reads your own bank & e-wallet
notifications, auto-categorizes them, and forecasts your end-of-month balance.

The parsing and analytics core (:mod:`dompet.core`, :mod:`dompet.analytics`) is
pure standard library and imports without Postgres, FastAPI, scikit-learn, or any
other third-party package. The service layer (:mod:`dompet.api`,
:mod:`dompet.dashboard`) and the model training (:mod:`dompet.ml`) pull those in.
"""

__version__ = "0.1.0"
