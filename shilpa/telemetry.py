"""Optional OpenTelemetry export to Azure Monitor / Application Insights.

Active only when APPLICATIONINSIGHTS_CONNECTION_STRING is set and the optional ``telemetry`` extra
(azure-monitor-opentelemetry) is installed; otherwise a no-op. Log redaction is re-attached to every handler the
exporter adds, so prompts and tokens do not leave the process through it either.
"""

from __future__ import annotations

import logging

from .logging_setup import attach_redaction

log = logging.getLogger("shilpa.telemetry")


def setup_telemetry(app=None, connection_string: str | None = None) -> bool:
    from . import settings as cfg

    cs = connection_string if connection_string is not None else cfg.hosting.appinsights_connection_string
    if not cs:
        return False
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
    except ImportError:
        log.warning("APPLICATIONINSIGHTS_CONNECTION_STRING is set but azure-monitor-opentelemetry is not installed "
                    "(install the 'telemetry' extra); telemetry export is off")
        return False
    try:
        configure_azure_monitor(connection_string=cs)
        if app is not None:
            try:
                from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

                FastAPIInstrumentor.instrument_app(app)
            except Exception:
                log.warning("FastAPI instrumentation unavailable")
    except Exception as e:
        log.warning("telemetry setup failed: %s", type(e).__name__)
        return False
    attach_redaction()
    return True
