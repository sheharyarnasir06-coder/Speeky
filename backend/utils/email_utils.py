import os
from email.message import EmailMessage
from html import escape
from io import BytesIO
from pathlib import Path

import aiosmtplib
from PIL import Image


INLINE_LOGO_CID = "speeky-logo"
PREVIEW_PADDING = "&zwnj;&nbsp;" * 120


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


def _local_logo_path() -> Path:
    return Path(__file__).resolve().parents[2] / "frontend" / "public" / "logo-icon.png"


def _use_inline_logo() -> bool:
    return not os.environ.get("EMAIL_LOGO_URL", "").strip() and _local_logo_path().exists()


def _render_white_logo_bytes() -> bytes:
    with Image.open(_local_logo_path()).convert("RGBA") as image:
        alpha = image.getchannel("A")
        white_logo = Image.new("RGBA", image.size, (255, 255, 255, 0))
        white_logo.putalpha(alpha)

        output = BytesIO()
        white_logo.save(output, format="PNG")
        return output.getvalue()


def _attach_inline_logo(msg: EmailMessage) -> None:
    if not _use_inline_logo():
        return

    try:
        html_part = msg.get_payload()[-1]
        html_part.add_related(
            _render_white_logo_bytes(),
            maintype="image",
            subtype="png",
            cid=f"<{INLINE_LOGO_CID}>",
        )
    except Exception:
        # Logo rendering should never block transactional email delivery.
        pass


def _render_template(heading: str, body_html: str) -> str:
    """Speeky-branded transactional email shell shared by every email."""
    logo_url = os.environ.get("EMAIL_LOGO_URL", "").strip()
    logo_src = f"cid:{INLINE_LOGO_CID}" if _use_inline_logo() else logo_url
    logo_html = (
        f'<img src="{escape(logo_src, quote=True)}" alt="" class="logo">'
        if logo_src
        else ""
    )
    logo_cell_html = (
        f'<td class="logo-cell">{logo_html}</td>'
        if logo_html
        else ""
    )
    fallback_brand_class = "" if logo_html else " brand-without-logo"

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            .preheader {{
                display: none !important;
                visibility: hidden;
                opacity: 0;
                color: transparent;
                height: 0;
                width: 0;
                max-height: 0;
                max-width: 0;
                overflow: hidden;
                mso-hide: all;
            }}
            body {{
                font-family: Inter, 'Segoe UI', Arial, sans-serif;
                background-color: #eef5f7;
                color: #071821;
                margin: 0;
                padding: 0;
                -webkit-font-smoothing: antialiased;
            }}
            .wrapper {{
                width: 100%;
                background: #eef5f7;
                padding: 48px 16px;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #ffffff;
                border-radius: 24px;
                box-shadow: 0 20px 60px rgba(5, 33, 46, 0.12);
                overflow: hidden;
                border: 1px solid #d5e5eb;
            }}
            .header {{
                background: #071821;
                padding: 30px 36px;
                text-align: left;
            }}
            .brand-row {{
                width: 100%;
                border-collapse: collapse;
            }}
            .logo-cell {{
                width: 58px;
                vertical-align: middle;
                padding: 0 16px 0 0;
            }}
            .brand-cell {{
                vertical-align: middle;
                padding: 0;
            }}
            .brand {{
                color: #ffffff;
                font-family: Georgia, 'Times New Roman', serif;
                font-size: 28px;
                font-weight: 700;
                line-height: 1.1;
                margin: 0;
                letter-spacing: -0.5px;
            }}
            .brand-without-logo {{
                text-align: left;
            }}
            .logo {{
                display: block;
                width: 46px;
                height: 46px;
                margin: 0;
            }}
            .tagline {{
                color: #9edce8;
                font-size: 13px;
                letter-spacing: 1.8px;
                margin: 5px 0 0;
                text-transform: uppercase;
            }}
            .content {{
                padding: 42px 42px 34px;
            }}
            .content h2 {{
                color: #071821;
                font-family: Georgia, 'Times New Roman', serif;
                font-size: 28px;
                line-height: 1.2;
                margin-top: 0;
                margin-bottom: 16px;
                font-weight: 700;
                letter-spacing: -0.4px;
            }}
            .content p {{
                font-size: 16px;
                line-height: 1.6;
                color: #476173;
                margin: 0 0 18px;
            }}
            .button-container {{
                text-align: center;
                margin: 34px 0;
            }}
            .button {{
                display: inline-block;
                padding: 14px 32px;
                background-color: #55c7dc;
                color: #071821 !important;
                text-decoration: none;
                border-radius: 999px;
                font-weight: 700;
                font-size: 16px;
                letter-spacing: 0.1px;
            }}
            .otp-code {{
                text-align: center;
                margin: 34px 0;
                font-size: 40px;
                line-height: 1;
                font-weight: 800;
                letter-spacing: 10px;
                color: #07556b;
                background: #e5f8fc;
                padding: 24px 18px;
                border-radius: 18px;
                border: 1px solid #bdebf4;
            }}
            .security-notice {{
                background-color: #f6fafb;
                border: 1px solid #dbe9ee;
                padding: 16px 18px;
                margin-top: 28px;
                border-radius: 16px;
            }}
            .security-notice p {{
                margin: 0;
                font-size: 14px;
                color: #516879;
            }}
            .footer {{
                background-color: #f6fafb;
                padding: 28px 40px;
                text-align: center;
                border-top: 1px solid #dbe9ee;
            }}
            .footer p {{
                font-size: 13px;
                color: #78909c;
                margin: 5px 0;
                line-height: 1.5;
            }}
            .link-fallback {{
                margin-top: 25px;
                padding-top: 20px;
                border-top: 1px dashed #d5e5eb;
                font-size: 14px;
                color: #5f7888;
                word-break: break-all;
            }}
        </style>
    </head>
    <body>
        <div class="preheader">Open this email to view your Speeky verification code. It expires soon and should never be shared.{PREVIEW_PADDING}</div>
        <div class="wrapper">
            <div class="container">
                <div class="header">
                    <table class="brand-row" role="presentation" cellpadding="0" cellspacing="0">
                        <tr>
                            {logo_cell_html}
                            <td class="brand-cell{fallback_brand_class}">
                                <p class="brand">Speeky</p>
                                <p class="tagline">AI Communication Coach</p>
                            </td>
                        </tr>
                    </table>
                </div>
                <div class="content">
                    <h2>{heading}</h2>
                    {body_html}
                </div>
                <div class="footer">
                    <p>If you did not request this, please ignore this email or contact support if you have concerns.</p>
                    <p>&copy; Speeky AI - Private speaking practice, made calmer.</p>
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
    _attach_inline_logo(msg)

    await aiosmtplib.send(
        msg,
        hostname=cfg["hostname"],
        port=cfg["port"],
        username=cfg["username"],
        password=cfg["password"],
        use_tls=cfg["use_tls"],
        start_tls=cfg["start_tls"],
    )


async def send_otp_email(to: str, code: str) -> None:
    ttl = os.environ.get("OTP_TTL_MINUTES", "10")

    body_html = f"""
    <p>You&apos;re one step away from starting your private speaking practice.</p>
    <p>Use this verification code to finish creating your Speeky account.</p>
    <div class="otp-code">{code}</div>
    <div class="security-notice">
        <p><strong>Note:</strong> This code expires in <strong>{ttl} minutes</strong>. Never share it with anyone.</p>
    </div>
    """

    await _send_email(
        to=to,
        subject="Your Speeky verification code",
        heading="Verify your Speeky account",
        body_html=body_html,
        text_body=(
            "Open this email to view your Speeky verification code.\n\n"
            f"For your security, the code is only shown inside the formatted email. "
            f"It expires in {ttl} minutes and should never be shared."
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
            "Open this email to view your Speeky email-change verification code.\n\n"
            f"For your security, the code is only shown inside the formatted email. "
            f"It expires in {ttl} minutes. Your current email stays active until "
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
