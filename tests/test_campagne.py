from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pere_noel_fremo.annonce import format_annonce_body, format_annonce_text, send_annonces
from pere_noel_fremo.campagne import (
    ExpediteurGmail,
    ExpediteurMemoire,
    Rendu,
    avancer_edition,
    avec_adresses_de_repli,
    cibler,
    envoyer_campagne,
)
from pere_noel_fremo.database import get_db_connection, init_db
from pere_noel_fremo.edition import StatutEdition, statut
from pere_noel_fremo.helper import EmailSendError

BASE = "https://noel.fremo.fr"
GABARIT = "<p>Bonjour {fullname}, ton lien : {magic_url}</p>"


def _rendu() -> Rendu:
    return Rendu(
        objet="Objet de test",
        html=lambda nom, lien: format_annonce_body(GABARIT, nom, lien, 2026),
        texte=lambda nom, lien: format_annonce_text(nom, lien, 2026),
    )


def _db(tmp_path: Path, lutins: dict[str, dict[str, Any]]) -> Path:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    conn = get_db_connection(db_path)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
        for lutin_id, params in lutins.items():
            conn.execute(
                "INSERT INTO lutins (id, fullname, email) VALUES (?, ?, ?);",
                (lutin_id, params["fullname"], params.get("email")),
            )
    conn.close()
    return db_path


def _sent_at(db_path: Path, lutin_id: str) -> Any:
    conn = get_db_connection(db_path)
    row = conn.execute("SELECT sent_at FROM tokens WHERE lutin_id = ?;", (lutin_id,)).fetchone()
    conn.close()
    return row["sent_at"]


LUTINS = {
    "a": {"fullname": "Lutin A", "email": "a@fremo.org"},
    "b": {"fullname": "Lutin B", "email": "b@fremo.org"},
}


def test_envoi_nominal_pose_sent_at_et_envoie_le_lien_magique(tmp_path: Path) -> None:
    db_path = _db(tmp_path, LUTINS)
    exp = ExpediteurMemoire()

    bilan = envoyer_campagne(db_path, 2026, LUTINS, _rendu(), exp, base_url=BASE)

    assert (bilan.envoyes, bilan.sans_email, bilan.echecs) == (2, 0, 0)
    assert [m.destinataire for m in exp.messages] == ["a@fremo.org", "b@fremo.org"]
    assert all(m.objet == "Objet de test" for m in exp.messages)
    assert f"{BASE}/lutin/" in exp.messages[0].html
    assert f"{BASE}/lutin/" in exp.messages[0].texte
    assert _sent_at(db_path, "a") is not None
    assert _sent_at(db_path, "b") is not None


def test_dry_run_n_envoie_aucun_message_et_ne_marque_rien(tmp_path: Path) -> None:
    db_path = _db(tmp_path, LUTINS)
    exp = ExpediteurMemoire()

    bilan = envoyer_campagne(db_path, 2026, LUTINS, _rendu(), exp, base_url=BASE, dry_run=True)

    assert bilan.envoyes == 2
    assert exp.messages == []
    assert _sent_at(db_path, "a") is None


def test_echec_d_un_destinataire_n_interrompt_pas_les_autres(tmp_path: Path) -> None:
    db_path = _db(tmp_path, LUTINS)
    exp = ExpediteurMemoire(echouer_pour=["a@fremo.org"])

    bilan = envoyer_campagne(db_path, 2026, LUTINS, _rendu(), exp, base_url=BASE)

    assert (bilan.envoyes, bilan.echecs) == (1, 1)
    assert [m.destinataire for m in exp.messages] == ["b@fremo.org"]
    assert _sent_at(db_path, "a") is None
    assert _sent_at(db_path, "b") is not None


def test_override_email_redirige_tous_les_messages(tmp_path: Path) -> None:
    db_path = _db(tmp_path, LUTINS)
    exp = ExpediteurMemoire()

    envoyer_campagne(db_path, 2026, LUTINS, _rendu(), exp, base_url=BASE, override_email="test@fremo.org")

    assert [m.destinataire for m in exp.messages] == ["test@fremo.org", "test@fremo.org"]


def test_lutin_sans_adresse_est_compte_sans_email(tmp_path: Path) -> None:
    lutins = {"a": {"fullname": "Lutin A", "email": None}}
    db_path = _db(tmp_path, lutins)
    exp = ExpediteurMemoire()

    bilan = envoyer_campagne(db_path, 2026, lutins, _rendu(), exp, base_url=BASE)

    assert (bilan.envoyes, bilan.sans_email, bilan.echecs) == (0, 1, 0)
    assert exp.messages == []


def test_nom_echappe_dans_le_html_mais_pas_dans_le_texte(tmp_path: Path) -> None:
    nom = "Zoé <b>&"
    lutins = {"z": {"fullname": nom, "email": "z@fremo.org"}}
    db_path = _db(tmp_path, lutins)
    exp = ExpediteurMemoire()

    envoyer_campagne(db_path, 2026, lutins, _rendu(), exp, base_url=BASE)

    message = exp.messages[0]
    assert "Zoé &lt;b&gt;&amp;" in message.html
    assert nom not in message.html
    assert nom in message.texte


def test_expediteur_memoire_ne_leve_que_pour_les_adresses_en_echec() -> None:
    exp = ExpediteurMemoire(echouer_pour=["x@fremo.org"])
    with pytest.raises(EmailSendError):
        exp.envoyer("x@fremo.org", "o", "h", "t")
    exp.envoyer("y@fremo.org", "o", "h", "t")
    assert len(exp.messages) == 1


def test_expediteur_gmail_construit_le_service_une_seule_fois() -> None:
    with (
        patch("pere_noel_fremo.helper.try_build_gmail_service", return_value=("svc", None)) as build,
        patch("pere_noel_fremo.helper.gmail_send_email") as send,
    ):
        exp = ExpediteurGmail("pere@fremo.org", "l'Annonce", interactive=True)
        build.assert_not_called()
        exp.envoyer("a@fremo.org", "Objet", "<p>h</p>", "t")
        exp.envoyer("b@fremo.org", "Objet", "<p>h</p>", "t")

    build.assert_called_once_with("l'Annonce", interactive=True)
    assert send.call_count == 2
    assert send.call_args.args[0] == "svc"
    assert send.call_args.kwargs == {
        "sender_email": "pere@fremo.org",
        "subject": "Objet",
        "body": "<p>h</p>",
        "toaddr": "b@fremo.org",
        "text_body": "t",
    }


def test_expediteur_gmail_leve_email_send_error_si_le_service_est_indisponible() -> None:
    with (
        patch("pere_noel_fremo.helper.try_build_gmail_service", return_value=(None, RuntimeError("quota"))),
        patch("pere_noel_fremo.helper.gmail_send_email") as send,
    ):
        exp = ExpediteurGmail("pere@fremo.org", "Révélation")
        with pytest.raises(EmailSendError):
            exp.envoyer("a@fremo.org", "o", "h", "t")

    send.assert_not_called()


def test_avec_adresses_de_repli_complete_depuis_secure_data() -> None:
    lutins: dict[str, dict[str, Any]] = {
        "a": {"fullname": "A", "email": None},
        "b": {"fullname": "B", "email": "b@x.org"},
    }
    secure = {"personnes": {"a": {"email": "a@secure.org"}, "b": {"email": "autre@secure.org"}}}

    resultat = avec_adresses_de_repli(lutins, secure)

    assert resultat["a"]["email"] == "a@secure.org"
    assert resultat["b"]["email"] == "b@x.org"
    assert avec_adresses_de_repli(lutins, {})["a"]["email"] is None


def test_cibler_restreint_ou_conserve_tout() -> None:
    assert list(cibler(LUTINS, ["b"])) == ["b"]
    assert list(cibler(LUTINS, None)) == ["a", "b"]
    assert list(cibler(LUTINS, [])) == ["a", "b"]


def test_avancer_edition_n_agit_que_depuis_le_statut_attendu(tmp_path: Path) -> None:
    db_path = _db(tmp_path, {})
    avancer_edition(db_path, 2026, StatutEdition.DRAWN, StatutEdition.REVEALED)
    assert statut(db_path, 2026) is StatutEdition.DRAFT
    avancer_edition(db_path, 2026, StatutEdition.DRAFT, StatutEdition.ANNOUNCED)
    assert statut(db_path, 2026) is StatutEdition.ANNOUNCED


@pytest.fixture
def fake_gmail_service() -> Iterator[MagicMock]:
    """Réservé aux tests d'ExpediteurGmail : aucun accès réel à Gmail/OAuth."""
    with patch("pere_noel_fremo.helper.build_gmail_service") as mock_build_service:
        yield mock_build_service


def _campagne_annonce(tmp_path: Path, **kwargs: Any) -> dict[str, int]:
    db_path = _db(tmp_path, {**LUTINS, "c": {"fullname": "Lutin C", "email": "c@fremo.org"}})
    return send_annonces(db_path=db_path, secure_data_path=tmp_path / "absent.yml", year=2026, **kwargs)


def test_expediteur_gmail_par_defaut_construit_le_service_une_fois_pour_toute_la_campagne(
    tmp_path: Path, fake_gmail_service: MagicMock
) -> None:
    with patch("pere_noel_fremo.helper.gmail_send_email") as mock_send:
        stats = _campagne_annonce(tmp_path)

    assert stats["sent"] == 3
    fake_gmail_service.assert_called_once_with(interactive=False)
    assert all(call.args[0] is fake_gmail_service.return_value for call in mock_send.call_args_list)


def test_expediteur_gmail_transmet_l_authentification_interactive(
    tmp_path: Path, fake_gmail_service: MagicMock
) -> None:
    with patch("pere_noel_fremo.helper.gmail_send_email"):
        _campagne_annonce(tmp_path, interactive_auth=True)

    fake_gmail_service.assert_called_once_with(interactive=True)


def test_expediteur_gmail_jeton_expire_echoue_vite_sans_navigateur(
    tmp_path: Path, fake_gmail_service: MagicMock
) -> None:
    fake_gmail_service.side_effect = EmailSendError("Jeton Gmail invalide : ré-authentifier en local")

    with (
        patch("pere_noel_fremo.helper.gmail_send_email") as mock_send,
        patch("pere_noel_fremo.helper.InstalledAppFlow") as mock_flow,
    ):
        stats = _campagne_annonce(tmp_path)

    assert (stats["echecs"], stats["sent"]) == (3, 0)
    mock_send.assert_not_called()
    mock_flow.from_client_secrets_file.assert_not_called()
    fake_gmail_service.assert_called_once()


@pytest.mark.parametrize(("dry_run", "no_email"), [(True, False), (False, True)])
def test_expediteur_gmail_simulation_ne_touche_jamais_aux_identifiants(
    tmp_path: Path, fake_gmail_service: MagicMock, dry_run: bool, no_email: bool
) -> None:
    stats = _campagne_annonce(tmp_path, dry_run=dry_run, no_email=no_email)

    assert stats["sent"] == 3
    fake_gmail_service.assert_not_called()
