"""
Email alerting via Resend API.

Requires env vars:
  RESEND_API_KEY   — from resend.com (free tier is enough)
  ALERT_FROM       — verified sender address, e.g. "Forkeur <alerts@yourdomain.com>"
                     (or leave unset to use Resend's sandbox: onboarding@resend.dev)
  ALERT_TO         — recipient address (defaults to geraud.marion@gmail.com)
"""
from __future__ import annotations
import logging
import os
from datetime import datetime, timezone, timedelta

import httpx

logger = logging.getLogger(__name__)

_RESEND_URL = "https://api.resend.com/emails"
_DEFAULT_TO = "geraud.marion@gmail.com"
_DEFAULT_FROM = "Forkeur Alerts <onboarding@resend.dev>"


def _cfg() -> tuple[str, str, str]:
    api_key = os.getenv("RESEND_API_KEY", "")
    from_addr = os.getenv("ALERT_FROM", _DEFAULT_FROM)
    to_addr = os.getenv("ALERT_TO", _DEFAULT_TO)
    return api_key, from_addr, to_addr


def _send(subject: str, html: str) -> None:
    api_key, from_addr, to_addr = _cfg()
    if not api_key:
        logger.warning("alerting: RESEND_API_KEY not set, skipping email")
        return
    try:
        resp = httpx.post(
            _RESEND_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"from": from_addr, "to": [to_addr], "subject": subject, "html": html},
            timeout=10,
        )
        if resp.status_code >= 400:
            logger.error("alerting: Resend returned %d — %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.error("alerting: failed to send email: %s", exc)


# ── Instant failure alert ─────────────────────────────────────────────────────

def send_failure_alert(platform: str, error_msg: str, run_id: str) -> None:
    """Fire immediately when a scraper finishes with status failed/blocked."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    short_err = (error_msg or "unknown error")[:300]
    subject = f"⚠️ Forkeur: {platform} scraper failed"
    html = f"""
<h2 style="color:#c0392b">⚠️ {platform} scraper failed</h2>
<table style="border-collapse:collapse;font-family:monospace;font-size:14px">
  <tr><td style="padding:4px 12px 4px 0;color:#666">Platform</td><td><strong>{platform}</strong></td></tr>
  <tr><td style="padding:4px 12px 4px 0;color:#666">Time</td><td>{now}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;color:#666">Run ID</td><td>{run_id}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;color:#666">Error</td><td style="color:#c0392b">{short_err}</td></tr>
</table>
"""
    _send(subject, html)


# ── Daily digest ──────────────────────────────────────────────────────────────

def send_daily_digest() -> None:
    """Send a morning status summary for all core scraper platforms."""
    import db

    platforms = ("ubereats", "deliveroo", "takeaway")
    cutoff_ok = datetime.now(timezone.utc) - timedelta(hours=25)
    rows_html = ""
    any_problem = False

    for platform in platforms:
        run = db.get_last_successful_run(platform)
        if run is None:
            status_html = '<span style="color:#c0392b">never run</span>'
            last_html = "—"
            any_problem = True
        else:
            finished = (run.get("finished_at") or run.get("started_at", "")).replace("Z", "+00:00")
            ts = datetime.fromisoformat(finished)
            age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
            last_html = ts.strftime("%Y-%m-%d %H:%M UTC")
            if ts < cutoff_ok:
                status_html = f'<span style="color:#c0392b">stale ({age_h:.0f}h ago)</span>'
                any_problem = True
            else:
                status_html = '<span style="color:#27ae60">ok</span>'

        saved = run["records_saved"] if run else 0
        rows_html += f"""
  <tr>
    <td style="padding:6px 16px 6px 0;font-weight:bold">{platform}</td>
    <td style="padding:6px 16px 6px 0">{status_html}</td>
    <td style="padding:6px 16px 6px 0;color:#666">{last_html}</td>
    <td style="padding:6px 16px 6px 0;color:#666">{saved} records</td>
  </tr>"""

    overall = "⚠️ Issues detected" if any_problem else "✅ All systems ok"
    subject = f"Forkeur daily status — {overall}"
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    html = f"""
<h2>Forkeur scraper status — {date_str}</h2>
<p style="font-size:16px">{overall}</p>
<table style="border-collapse:collapse;font-family:sans-serif;font-size:14px">
  <thead>
    <tr style="border-bottom:2px solid #ddd">
      <th style="padding:6px 16px 6px 0;text-align:left">Platform</th>
      <th style="padding:6px 16px 6px 0;text-align:left">Status</th>
      <th style="padding:6px 16px 6px 0;text-align:left">Last success</th>
      <th style="padding:6px 16px 6px 0;text-align:left">Records</th>
    </tr>
  </thead>
  <tbody>{rows_html}</tbody>
</table>
"""
    _send(subject, html)
