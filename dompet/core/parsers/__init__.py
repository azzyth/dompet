"""Bank / e-wallet notification parsers."""

from dompet.core.parsers import bank_generic, bca, ewallet, mandiri
from dompet.core.parsers.registry import detect_source, parse

__all__ = ["detect_source", "parse", "bca", "mandiri", "ewallet", "bank_generic"]
