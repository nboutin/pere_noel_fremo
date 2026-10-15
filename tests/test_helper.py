import base64
import logging
from email import message_from_bytes
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pere_noel_fremo.helper import (
    LOGS_DIR,
    build_gmail_service,
    configure_logger,
    create_message,
    gmail_send_email,
    load_credentials,
    try_build_gmail_service,
)


def test_try_build_gmail_service_returns_service_on_success() -> None:
    with patch("pere_noel_fremo.helper.build_gmail_service", return_value="svc") as mock_build:
        service, error = try_build_gmail_service("Annonce", interactive=True)
    assert (service, error) == ("svc", None)
    mock_build.assert_called_once_with(interactive=True)


def test_try_build_gmail_service_returns_error_and_logs_on_failure(caplog: pytest.LogCaptureFixture) -> None:
    boom = RuntimeError("pas de jeton")
    with patch("pere_noel_fremo.helper.build_gmail_service", side_effect=boom), caplog.at_level(logging.ERROR):
        service, error = try_build_gmail_service("Révélation")
    assert service is None
    assert error is boom
    assert "Révélation" in caplog.text
    assert "service Gmail indisponible" in caplog.text


def test_create_message_structure_without_image() -> None:
    sender = "pere_noel@fremo.org"
    subject = "Ho Ho Ho"
    body = "<p>Tu offres un cadeau à quelqu'un !</p>"
    recipient = "lutin@fremo.org"

    msg_dict = create_message(sender, subject, body, recipient, None)

    assert "raw" in msg_dict
    raw_decoded = base64.urlsafe_b64decode(msg_dict["raw"])
    email_msg = message_from_bytes(raw_decoded)

    assert email_msg["From"] == sender
    assert email_msg["Subject"] == subject
    assert email_msg["To"] == recipient
    assert email_msg.is_multipart()


def test_create_message_with_image(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sender = "pere_noel@fremo.org"
    subject = "Ho Ho Ho avec image"
    body = "<p>Message</p>"
    recipient = "lutin@fremo.org"

    # Création d'une fausse image pour le test
    dummy_img = tmp_path / "test.png"
    dummy_img.write_bytes(b"\x89PNG\r\n\x1a\nfakeimagebytes")

    msg_dict = create_message(sender, subject, body, recipient, str(dummy_img))
    raw_decoded = base64.urlsafe_b64decode(msg_dict["raw"])
    email_msg = message_from_bytes(raw_decoded)

    assert email_msg.is_multipart()
    # On doit retrouver la pièce jointe image avec le content-id
    payloads = email_msg.get_payload()
    content_types = [p.get_content_type() for p in payloads]  # type: ignore[union-attr]
    assert "image/png" in content_types or any("image" in ct for ct in content_types)


def test_gmail_send_email_uses_injected_service() -> None:
    mock_service = MagicMock()
    mock_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {
        "id": "12345",
        "status": "SENT",
    }

    with (
        patch("pere_noel_fremo.helper.load_credentials") as mock_load,
        patch("pere_noel_fremo.helper.build") as mock_build,
    ):
        res = gmail_send_email(mock_service, "from@test.com", "Test Subject", "Test Body", "to@test.com")

    assert res == {"id": "12345", "status": "SENT"}
    mock_load.assert_not_called()
    mock_build.assert_not_called()
    mock_service.users.return_value.messages.return_value.send.assert_called_once()


def test_create_message_with_text_body() -> None:
    sender = "pere_noel@fremo.org"
    subject = "Ho Ho Ho"
    body = "<h1>HTML Message</h1>"
    recipient = "lutin@fremo.org"
    magic_url = "https://noel.fremo.fr/lutin/magic-1234"
    text_body = f"Bonjour Lutin,\nVoici ton lien magique : {magic_url}"

    msg_dict = create_message(sender, subject, body, recipient, None, text_body=text_body)
    raw_decoded = base64.urlsafe_b64decode(msg_dict["raw"])
    email_msg = message_from_bytes(raw_decoded)

    plain_parts = []
    for part in email_msg.walk():
        if part.get_content_type() == "text/plain":
            payload = part.get_payload(decode=True)
            assert isinstance(payload, bytes)
            plain_parts.append(payload.decode("utf-8"))

    assert len(plain_parts) >= 1
    assert magic_url in plain_parts[0]
    assert "Bonjour Lutin" in plain_parts[0]


def test_gmail_send_email_raises_email_send_error_on_failure() -> None:
    import pytest
    from pere_noel_fremo.helper import EmailSendError

    mock_service = MagicMock()
    mock_service.users.return_value.messages.return_value.send.return_value.execute.side_effect = RuntimeError(
        "Quota Gmail dépassé"
    )

    with pytest.raises(EmailSendError) as exc_info:
        gmail_send_email(mock_service, "from@test.com", "Subject", "Body", "target@test.com")

    assert "target@test.com" in str(exc_info.value)
    assert "Quota Gmail dépassé" in str(exc_info.value)


def test_build_gmail_service_builds_service_from_credentials() -> None:
    with (
        patch("pere_noel_fremo.helper.load_credentials") as mock_load,
        patch("pere_noel_fremo.helper.build") as mock_build,
    ):
        service = build_gmail_service()

    mock_load.assert_called_once_with(interactive=False)
    mock_build.assert_called_once_with("gmail", "v1", credentials=mock_load.return_value)
    assert service is mock_build.return_value


def test_load_credentials_non_interactive_without_token_raises_and_never_opens_browser(tmp_path: Path) -> None:
    import pytest
    from pere_noel_fremo.helper import EmailSendError

    with (
        patch("pere_noel_fremo.helper.get_token_path", return_value=tmp_path / "absent.json"),
        patch("pere_noel_fremo.helper.get_credentials_path", return_value=tmp_path / "secret.json"),
        patch("pere_noel_fremo.helper.InstalledAppFlow") as mock_flow,
        pytest.raises(EmailSendError, match="Jeton Gmail invalide : ré-authentifier en local"),
    ):
        load_credentials()

    mock_flow.from_client_secrets_file.assert_not_called()


def test_load_credentials_non_interactive_with_unrefreshable_token_never_opens_browser(tmp_path: Path) -> None:
    import pytest
    from pere_noel_fremo.helper import EmailSendError

    token_path = tmp_path / "token.json"
    token_path.write_text("{}", encoding="utf-8")
    expired = MagicMock(valid=False, expired=True, refresh_token=None)

    with (
        patch("pere_noel_fremo.helper.get_token_path", return_value=token_path),
        patch("pere_noel_fremo.helper.Credentials") as mock_creds_cls,
        patch("pere_noel_fremo.helper.InstalledAppFlow") as mock_flow,
    ):
        mock_creds_cls.from_authorized_user_file.return_value = expired
        with pytest.raises(EmailSendError, match="Jeton Gmail invalide"):
            load_credentials()

    mock_flow.from_client_secrets_file.assert_not_called()


def test_load_credentials_interactive_opens_local_server_when_token_absent(tmp_path: Path) -> None:
    fake_creds = MagicMock()
    fake_creds.to_json.return_value = "{}"
    token_path = tmp_path / "token.json"

    with (
        patch("pere_noel_fremo.helper.get_token_path", return_value=token_path),
        patch("pere_noel_fremo.helper.get_credentials_path", return_value=tmp_path / "secret.json"),
        patch("pere_noel_fremo.helper.InstalledAppFlow") as mock_flow,
    ):
        mock_flow.from_client_secrets_file.return_value.run_local_server.return_value = fake_creds
        creds = load_credentials(interactive=True)

    assert creds is fake_creds
    assert token_path.exists()


def test_configure_logger_creates_file_in_logs_dir() -> None:
    test_log_filename = "test_execution.log"
    configure_logger(test_log_filename)

    assert LOGS_DIR.exists()
    assert LOGS_DIR.is_dir()
    expected_log_path = LOGS_DIR / test_log_filename
    assert expected_log_path.exists()

    # Fermeture et détachement du handler pour libérer le fichier sous Windows
    root_logger = logging.getLogger("")
    for handler in list(root_logger.handlers):
        if isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", None) == str(
            expected_log_path.resolve()
        ):
            handler.close()
            root_logger.removeHandler(handler)

    expected_log_path.unlink(missing_ok=True)


def test_format_date_repas_none_or_empty() -> None:
    from pere_noel_fremo.helper import format_date_repas

    assert format_date_repas(None) is None
    assert format_date_repas("") is None
    assert format_date_repas("   ") is None


def test_format_date_repas_future_current_and_past() -> None:
    from datetime import date

    from pere_noel_fremo.helper import format_date_repas

    target_date = "2026-12-05"

    # 1. Date future (52 jours avant)
    ref_future = date(2026, 10, 14)
    info_future = format_date_repas(target_date, now=ref_future)
    assert info_future is not None
    assert info_future["raw"] == "2026-12-05"
    assert info_future["formatted"] == "samedi 5 décembre 2026"
    assert info_future["delta_days"] == 52
    assert info_future["countdown"] == "J-52"

    # 2. Jour J
    ref_today = date(2026, 12, 5)
    info_today = format_date_repas(target_date, now=ref_today)
    assert info_today is not None
    assert info_today["delta_days"] == 0
    assert info_today["countdown"] == "Aujourd'hui ! 🎅"

    # 3. Date passée
    ref_past = date(2026, 12, 6)
    info_past = format_date_repas(target_date, now=ref_past)
    assert info_past is not None
    assert info_past["delta_days"] == -1
    assert info_past["countdown"] == "Passé"
