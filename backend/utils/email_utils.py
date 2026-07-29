import os
from email.message import EmailMessage
from typing import Iterable, Optional, Tuple

import aiosmtplib


def _get_transport_config() -> dict:
    # nodemailer's `secure` option: true = implicit TLS from connect (aiosmtplib use_tls);
    # false = plain connect, upgrade to STARTTLS only if the server offers it (aiosmtplib's
    # start_tls=None, its default "opportunistic" mode) — NOT start_tls=True, which means
    # "require STARTTLS, hard-fail if unsupported" and has no nodemailer equivalent here.
    secure = os.environ.get("SMTP_SECURE") == "true"
    return {
        "hostname": os.environ.get("SMTP_HOST"),
        "port": int(os.environ.get("SMTP_PORT", 587)),
        "username": os.environ.get("SMTP_USER"),
        "password": os.environ.get("SMTP_PASS"),
        "use_tls": secure,
        "start_tls": None if not secure else False,
    }


def _render_template(heading: str, body_html: str) -> str:
    """Generic business email shell shared by every transactional email."""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
                background-color: #f8f9fa;
                color: #1a1a1a;
                margin: 0;
                padding: 0;
                -webkit-font-smoothing: antialiased;
            }}
            .wrapper {{
                width: 100%;
                background-color: #f8f9fa;
                padding: 40px 0;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #ffffff;
                border-radius: 8px;
                box-shadow: 0 2px 10px rgba(0, 0, 0, 0.08);
                overflow: hidden;
                border-top: 4px solid #1a3673;
            }}
            .header {{
                padding: 40px 30px 20px;
                text-align: center;
                border-bottom: 1px solid #e9ecef;
            }}
            .logo {{
                max-width: 150px;
                height: auto;
            }}
            .content {{
                padding: 40px 40px 30px;
            }}
            .content h2 {{
                color: #1a3673;
                font-size: 22px;
                margin-top: 0;
                margin-bottom: 20px;
                font-weight: 600;
            }}
            .content p {{
                font-size: 16px;
                line-height: 1.6;
                color: #4a4a4a;
                margin-bottom: 20px;
            }}
            .button-container {{
                text-align: center;
                margin: 35px 0;
            }}
            .button {{
                display: inline-block;
                padding: 14px 32px;
                background-color: #1a3673;
                color: #ffffff !important;
                text-decoration: none;
                border-radius: 4px;
                font-weight: 600;
                font-size: 16px;
                letter-spacing: 0.5px;
            }}
            .otp-code {{
                text-align: center;
                margin: 35px 0;
                font-size: 36px;
                font-weight: 700;
                letter-spacing: 8px;
                color: #1a3673;
                background-color: #f4f6f9;
                padding: 20px;
                border-radius: 4px;
            }}
            .security-notice {{
                background-color: #f4f6f9;
                border-left: 4px solid #c0392b;
                padding: 15px 20px;
                margin-top: 30px;
                border-radius: 0 4px 4px 0;
            }}
            .security-notice p {{
                margin: 0;
                font-size: 14px;
                color: #555555;
            }}
            .footer {{
                background-color: #f8f9fa;
                padding: 30px 40px;
                text-align: center;
                border-top: 1px solid #e9ecef;
            }}
            .footer p {{
                font-size: 13px;
                color: #888888;
                margin: 5px 0;
                line-height: 1.5;
            }}
            .link-fallback {{
                margin-top: 25px;
                padding-top: 20px;
                border-top: 1px dashed #e9ecef;
                font-size: 14px;
                color: #666666;
                word-break: break-all;
            }}
        </style>
    </head>
    <body>
        <div class="wrapper">
            <div class="container">
                <div class="header">
                    <img src="https://i.pinimg.com/736x/55/4c/6c/554c6cf1a4954619965be76b7d1163cc.jpg" alt="Speeky AI Logo" class="logo">
                </div>
                <div class="content">
                    <h2>{heading}</h2>
                    {body_html}
                </div>
                <div class="footer">
                    <p>If you did not request this, please ignore this email or contact support if you have concerns.</p>
                    <p>&copy; Speeky AI - Assisted English Language Practice</p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """


async def _send_email(to: str, subject: str, heading: str, body_html: str, text_body: str) -> None:
    cfg = _get_transport_config()

    msg = EmailMessage()
    msg["From"] = os.environ.get("SMTP_FROM", '"Speeky AI" <no-reply@speeky.ai>')
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text_body)
    msg.add_alternative(_render_template(heading, body_html), subtype="html")

    await aiosmtplib.send(
        msg,
        hostname=cfg["hostname"],
        port=cfg["port"],
        username=cfg["username"],
        password=cfg["password"],
        use_tls=cfg["use_tls"],
        start_tls=cfg["start_tls"],
    )


async def _send_email_with_attachment(
    to: str,
    subject: str,
    heading: str,
    body_html: str,
    text_body: str,
    attachment: Optional[Tuple[str, bytes, str]] = None,  # (filename, content, mime_subtype)
) -> None:
    """Same shell as `_send_email`, plus one optional file attachment — used by
    the scheduled-report email (GAP-04) where `_send_email` has no attachment
    support today."""
    cfg = _get_transport_config()

    msg = EmailMessage()
    msg["From"] = os.environ.get("SMTP_FROM", '"Speeky AI" <no-reply@speeky.ai>')
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text_body)
    msg.add_alternative(_render_template(heading, body_html), subtype="html")

    if attachment:
        filename, content, subtype = attachment
        maintype = "application" if subtype in ("pdf", "octet-stream") else "text"
        msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)

    await aiosmtplib.send(
        msg,
        hostname=cfg["hostname"],
        port=cfg["port"],
        username=cfg["username"],
        password=cfg["password"],
        use_tls=cfg["use_tls"],
        start_tls=cfg["start_tls"],
    )


# ── GAP-03 (US-201): Anomaly alert delivery ──────────────────────────────────
async def send_anomaly_alert_email(to: str, metric_label: str, value: float, baseline: float, deviation: float, dashboard_url: str) -> None:
    body_html = f"""
    <p>An anomaly was detected in <strong>{metric_label}</strong>.</p>
    <ul>
        <li>Current value: <strong>{value}</strong></li>
        <li>Expected (baseline): <strong>{round(baseline, 2)}</strong></li>
        <li>Deviation: <strong>{round(deviation, 2)}</strong></li>
    </ul>
    <div class="button-container">
        <a href="{dashboard_url}" class="button">View on Dashboard</a>
    </div>
    """
    await _send_email(
        to=to,
        subject=f"[Speeky Alert] Anomaly detected in {metric_label}",
        heading="Anomaly Detected",
        body_html=body_html,
        text_body=(
            f"Anomaly detected in {metric_label}: value={value}, baseline={round(baseline, 2)}, "
            f"deviation={round(deviation, 2)}.\n\nView filtered dashboard: {dashboard_url}"
        ),
    )


async def send_alert_digest_email(to: str, breaches: Iterable[dict], dashboard_url: str) -> None:
    """E-01: one email for N simultaneous breaches instead of N separate emails."""
    breaches = list(breaches)
    items_html = "".join(
        f"<li><strong>{b['metric_label']}</strong>: {b['value']} (baseline {round(b['baseline'], 2)})</li>"
        for b in breaches
    )
    body_html = f"""
    <p>{len(breaches)} metrics were affected around the same time — grouped into one digest so this doesn't look like {len(breaches)} unrelated incidents.</p>
    <ul>{items_html}</ul>
    <div class="button-container">
        <a href="{dashboard_url}" class="button">View on Dashboard</a>
    </div>
    """
    await _send_email(
        to=to,
        subject=f"[Speeky Alert] {len(breaches)} metrics affected — possible outage",
        heading="Multiple Metrics Affected",
        body_html=body_html,
        text_body=f"{len(breaches)} metrics breached together: " + ", ".join(b["metric_label"] for b in breaches) + f"\n\n{dashboard_url}",
    )


async def send_alert_resolved_email(to: str, metric_label: str, dashboard_url: str) -> None:
    """E-05: exactly one resolution notice when an ongoing incident normalizes."""
    body_html = f"""
    <p><strong>{metric_label}</strong> has returned to its normal range. No further action needed.</p>
    <div class="button-container">
        <a href="{dashboard_url}" class="button">View on Dashboard</a>
    </div>
    """
    await _send_email(
        to=to,
        subject=f"[Speeky Alert] {metric_label} back to normal",
        heading="Anomaly Resolved",
        body_html=body_html,
        text_body=f"{metric_label} has returned to its normal range.\n\n{dashboard_url}",
    )


async def send_unassigned_alert_email(to: str, metric_label: str, dashboard_url: str) -> None:
    """E-04: notifies a Super Admin that a breaching metric has no owner configured."""
    body_html = f"""
    <p><strong>{metric_label}</strong> breached its expected range, but no admin is configured to own alerts for it.</p>
    <p>Please assign an owner in threshold settings so future breaches reach the right person.</p>
    <div class="button-container">
        <a href="{dashboard_url}" class="button">View on Dashboard</a>
    </div>
    """
    await _send_email(
        to=to,
        subject=f"[Speeky Alert] Unassigned anomaly: {metric_label}",
        heading="Unassigned Alert Needs an Owner",
        body_html=body_html,
        text_body=f"{metric_label} breached with no configured owner. Assign one in threshold settings.\n\n{dashboard_url}",
    )


# ── GAP-04 (US-202): Scheduled report delivery ───────────────────────────────
async def send_report_email(to: str, report_name: str, attachment_filename: str, attachment_bytes: bytes, attachment_subtype: str) -> None:
    body_html = f"""
    <p>Your scheduled report <strong>{report_name}</strong> is attached.</p>
    """
    await _send_email_with_attachment(
        to=to,
        subject=f"Speeky Report: {report_name}",
        heading="Your Scheduled Report",
        body_html=body_html,
        text_body=f"Your scheduled report '{report_name}' is attached.",
        attachment=(attachment_filename, attachment_bytes, attachment_subtype),
    )


async def send_report_generation_failed_email(to: str, report_name: str, dashboard_url: str) -> None:
    """E-01: after 2 retries fail, tell the owner instead of failing silently."""
    body_html = f"""
    <p>We couldn't generate your scheduled report <strong>{report_name}</strong> after 3 attempts.</p>
    <p>View the dashboard directly in the meantime:</p>
    <div class="button-container">
        <a href="{dashboard_url}" class="button">View Dashboard</a>
    </div>
    """
    await _send_email(
        to=to,
        subject=f"Speeky Report failed: {report_name}",
        heading="Report Generation Failed",
        body_html=body_html,
        text_body=f"Report '{report_name}' failed to generate after 3 attempts. View the dashboard directly: {dashboard_url}",
    )


async def send_otp_email(to: str, code: str) -> None:
    ttl = os.environ.get("OTP_TTL_MINUTES", "10")

    body_html = f"""
    <p>Hello,</p>
    <p>Use the verification code below to complete your Speeky AI signup.</p>
    <div class="otp-code">{code}</div>
    <div class="security-notice">
        <p><strong>Note:</strong> This code expires in <strong>{ttl} minutes</strong>. Never share it with anyone.</p>
    </div>
    """

    await _send_email(
        to=to,
        subject="Your Speeky AI verification code",
        heading="Verify Your Email",
        body_html=body_html,
        text_body=(
            f"Your Speeky AI verification code is: {code}\n\n"
            f"This code expires in {ttl} minutes. Never share it with anyone."
        ),
    )

    if os.environ.get("APP_ENV") != "production":
        print(f"[DEV] OTP code for {to}: {code}")


async def send_email_change_otp(to: str, code: str) -> None:
    ttl = os.environ.get("OTP_TTL_MINUTES", "10")

    body_html = f"""
    <p>Hello,</p>
    <p>Use the verification code below to confirm this new email address for your Speeky AI account.</p>
    <div class="otp-code">{code}</div>
    <div class="security-notice">
        <p><strong>Note:</strong> This code expires in <strong>{ttl} minutes</strong>. Your current email stays active until this is confirmed. Never share this code with anyone.</p>
    </div>
    """

    await _send_email(
        to=to,
        subject="Confirm your new Speeky AI email address",
        heading="Confirm Your New Email",
        body_html=body_html,
        text_body=(
            f"Your Speeky AI email-change verification code is: {code}\n\n"
            f"This code expires in {ttl} minutes. Your current email stays active until "
            "this is confirmed. Never share it with anyone."
        ),
    )

    if os.environ.get("APP_ENV") != "production":
        print(f"[DEV] Email-change OTP code for {to}: {code}")


async def send_password_reset_email(to: str, reset_url: str) -> None:
    ttl = os.environ.get("RESET_TOKEN_TTL_MINUTES", "15")

    body_html = f"""
    <p>Hello,</p>
    <p>We received a request to reset the password associated with your Speeky AI account. To proceed with resetting your password, please click the button below.</p>
    <div class="button-container">
        <a href="{reset_url}" class="button">Reset My Password</a>
    </div>
    <div class="security-notice">
        <p><strong>Note:</strong> This link is only valid for the next <strong>{ttl} minutes</strong> for your security.</p>
    </div>
    <div class="link-fallback">
        <p>If you're having trouble clicking the password reset button, copy and paste the URL below into your web browser:</p>
        <a href="{reset_url}" style="color: #1a3673;">{reset_url}</a>
    </div>
    """

    await _send_email(
        to=to,
        subject="Reset your Speeky AI password",
        heading="Password Reset Request",
        body_html=body_html,
        text_body=(
            f"You requested a password reset.\n\n"
            f"Click the link below (valid for {ttl} minutes):\n\n{reset_url}\n\n"
            f"If you did not request this, ignore this email."
        ),
    )

    if os.environ.get("APP_ENV") != "production":
        print(f"[DEV] Reset URL: {reset_url}")
