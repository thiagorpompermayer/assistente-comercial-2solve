"""Rotinas agendadas (APScheduler). Por ora: varredura diária de atrasos."""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from src.config import get_settings

logger = logging.getLogger(__name__)


def _run_monitor_scan() -> None:
    from src.agents.monitor_agent import MonitorAgent, build_overdue_demand
    from src.db.session import get_session_factory

    logger.info("scheduler: iniciando varredura de atrasos do monitor_agent")
    agent = MonitorAgent(get_session_factory())
    result = agent.run_demand(build_overdue_demand(), trigger="scheduler")
    logger.info("scheduler: varredura concluída (run %s, %s)", result.run_id, result.status)


def _run_email_triage() -> None:
    from src.agents.email_agent import EmailAgent, build_triage_demand
    from src.db.session import get_session_factory

    logger.info("scheduler: iniciando triagem da inbox pelo email_agent")
    agent = EmailAgent(get_session_factory())
    result = agent.run_demand(build_triage_demand(), trigger="scheduler")
    logger.info("scheduler: triagem concluída (run %s, %s)", result.run_id, result.status)


def create_scheduler() -> BackgroundScheduler:
    settings = get_settings()
    scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(
        _run_monitor_scan,
        trigger="cron",
        hour=settings.monitor_cron_hour,
        id="monitor_overdue_scan",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_email_triage,
        trigger="cron",
        hour=settings.email_triage_cron_hour,
        id="email_inbox_triage",
        replace_existing=True,
    )
    return scheduler
