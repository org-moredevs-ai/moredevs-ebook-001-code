"""Multi-channel alerting wrapper around Apprise.

PT: Permite a qualquer receita disparar alertas para Telegram, email,
Slack ou Microsoft Teams sem reimplementar a integração. As URLs Apprise
são lidas da variável de ambiente ``APPRISE_URLS`` (separadas por vírgulas,
formato Apprise — ver https://github.com/caronc/apprise).
EN: Lets any recipe push alerts to Telegram, email, Slack or MS Teams
without re-implementing the integration. Apprise URLs are read from the
``APPRISE_URLS`` env var (comma-separated, Apprise format — see
https://github.com/caronc/apprise).

The wrapper degrades gracefully when no URLs are configured: alerts are
logged at WARNING level and nothing else happens. This keeps demos and
tests deterministic without touching real channels.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Final

from apprise import Apprise, NotifyType

LOG = logging.getLogger("alerting")

SEVERITY_TO_NOTIFY: Final[dict[str, NotifyType]] = {
    "info": NotifyType.INFO,
    "warning": NotifyType.WARNING,
    "critical": NotifyType.FAILURE,
}


@dataclass(slots=True)
class AlertSender:
    """Resolves the Apprise URL list once and exposes :meth:`send`.

    PT: Resolve a lista de URLs Apprise uma vez e expõe :meth:`send`.
    EN: Resolves the Apprise URL list once and exposes :meth:`send`.

    Construct with :meth:`AlertSender.from_env` to pick the URLs up from
    ``APPRISE_URLS``. Pass an empty list to disable network delivery —
    alerts will still be logged.
    """

    apprise: Apprise
    has_urls: bool

    @classmethod
    def from_env(cls) -> AlertSender:
        raw = os.environ.get("APPRISE_URLS", "").strip()
        urls = [u.strip() for u in raw.split(",") if u.strip()]
        return cls.from_urls(urls)

    @classmethod
    def from_urls(cls, urls: list[str]) -> AlertSender:
        ap = Apprise()
        added = 0
        for url in urls:
            if ap.add(url):
                added += 1
            else:
                LOG.warning("Apprise rejected URL: %s", url)
        return cls(apprise=ap, has_urls=added > 0)

    def send(
        self,
        *,
        title: str,
        body: str,
        severity: str = "info",
    ) -> bool:
        """Dispatch one alert. Returns True on success or when no channels are wired.

        PT: Despacha um alerta. Devolve True se OK ou se não há canais.
        EN: Dispatches one alert. Returns True on success or when no channels.
        """
        notify_type = SEVERITY_TO_NOTIFY.get(severity, NotifyType.INFO)
        LOG.warning("[ALERT %s] %s — %s", severity.upper(), title, body)
        if not self.has_urls:
            return True
        try:
            ok = self.apprise.notify(
                body=body,
                title=title,
                notify_type=notify_type,
            )
        except Exception:
            # Apprise wraps a lot of network calls; we'd rather log and
            # carry on than crash the receiver loop.
            LOG.exception("Apprise notify failed; alert was logged only")
            return False
        return bool(ok)
