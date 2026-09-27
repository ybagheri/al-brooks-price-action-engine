"""Al Brooks Price Action Engine.

A production-grade, extensible, platform-independent price action analysis library
based on the systematic trading principles of Al Brooks.
"""

from albrooks.core.bars import Bar, BarSeries
from albrooks.engine.analyzer import Analyzer
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.engine.state import AnalysisResult
from albrooks.version import __version__

__all__ = [
    "__version__",
    "Bar",
    "BarSeries",
    "Analyzer",
    "AnalyzerConfig",
    "AnalysisResult",
]
