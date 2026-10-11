import base64
from email import message_from_bytes
from unittest.mock import MagicMock, patch

from pere_noel_fremo.helper import create_message, gmail_send_email


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


@patch("pere_noel_fremo.helper.load_credentials")
@patch("pere_noel_fremo.helper.build")
def test_gmail_send_email_mocked(mock_build: MagicMock, mock_load_credentials: MagicMock) -> None:
    mock_creds = MagicMock()
    mock_load_credentials.return_value = mock_creds

    mock_service = MagicMock()
    mock_users = MagicMock()
    mock_messages = MagicMock()
    mock_send = MagicMock()

    mock_build.return_value = mock_service
    mock_service.users.return_value = mock_users
    mock_users.messages.return_value = mock_messages
    mock_messages.send.return_value = mock_send
    mock_send.execute.return_value = {"id": "12345", "status": "SENT"}

    res = gmail_send_email("from@test.com", "Test Subject", "Test Body", "to@test.com")

    assert res == {"id": "12345", "status": "SENT"}
    mock_build.assert_called_once_with("gmail", "v1", credentials=mock_creds)
    mock_messages.send.assert_called_once()


def test_configure_logger_creates_file_in_logs_dir() -> None:
    from pere_noel_fremo.helper import LOGS_DIR, configure_logger

    test_log_filename = "test_execution.log"
    configure_logger(test_log_filename)

    assert LOGS_DIR.exists()
    assert LOGS_DIR.is_dir()
    expected_log_path = LOGS_DIR / test_log_filename
    assert expected_log_path.exists()
