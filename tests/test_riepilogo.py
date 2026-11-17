"""Test del parser dei riepiloghi per sezione, su righe reali dei file del Comune."""

from pathlib import Path

import pytest

from app.ingest.elezioni.riepilogo import ErroreFormato, leggi_riepilogo

DATI = Path(__file__).parent / "dati" / "elezioni"


def test_sindaco_2016_un_valore_per_candidato():
    r = leggi_riepilogo(DATI / "sindaco_2016.csv")
    assert r.titolo == "AMMINISTRATIVE 2016"
    assert r.scrutinate == (919, 919)
    assert len(r.soggetti) == 17
    assert r.soggetti[0].nome == "USSEGLIO VIRETTA Roberto"
    prima = r.affluenza.iloc[0].to_dict()
    assert prima == {
        "sezione": "1",
        "circoscrizione": "1",
        "scrutinata": True,
        "elettori": 968,
        "votanti": 521,
        "schede_bianche": 3,
        "schede_nulle": 4,
        "schede_contestate": 4,
        "voti_validi": 510,
    }
    sez1 = r.voti[r.voti.sezione == "1"]
    assert sez1["voti"].sum() == 510  # i voti ai candidati sommano ai validi


def test_sindaco_2021_due_valori_conta_il_primo():
    r = leggi_riepilogo(DATI / "sindaco_2021.csv")
    assert len(r.soggetti) == 13
    sez1 = r.voti[r.voti.sezione == "1"].set_index("soggetto")["voti"]
    assert sez1["Stefano LO RUSSO"] == 312  # non 21, che sono i "voti solo sindaco"
    assert sez1.sum() == r.affluenza.iloc[0]["voti_validi"] == 542
    assert "scrutinata" in r.affluenza and r.affluenza["scrutinata"].all()


def test_liste_2024_valori_tra_virgolette():
    r = leggi_riepilogo(DATI / "liste_europee_2024.csv")
    assert len(r.soggetti) == 12
    assert r.affluenza.iloc[0]["elettori"] == 958
    assert r.voti.groupby("sezione")["voti"].sum().iloc[0] == r.affluenza.iloc[0]["voti_validi"]


def test_preferenze_lista_dal_preambolo():
    r = leggi_riepilogo(DATI / "preferenze_2021.csv")
    assert r.lista is not None and r.lista.numero == 1
    assert r.lista.nome == "PARTITO COMUNISTA DEI LAVORATORI"
    # nei file di preferenze non ci sono votanti: le colonne restano vuote
    assert r.affluenza["votanti"].isna().all()
    assert (r.voti["voti"] >= 0).all()


def test_preferenze_cp1252():
    r = leggi_riepilogo(DATI / "preferenze_2016_cp1252.csv")
    assert r.lista.nome == "ABROGAZIONE!"
    assert all("�" not in s.nome for s in r.soggetti)


def test_uninominale_camera():
    r = leggi_riepilogo(DATI / "uninominale_camera_2022.csv")
    assert r.titolo == "CAMERA 2022"
    assert r.soggetti[0].nome == "TEVERE CARLOTTA"
    sez = r.voti.groupby("sezione")["voti"].sum()
    val = r.affluenza.set_index("sezione")["voti_validi"]
    assert (sez == val).all()


def test_sezione_non_scrutinata_segnalata():
    r = leggi_riepilogo(DATI / "liste_camera_2022.csv")
    assert r.scrutinate == (467, 468)
    riga = r.affluenza.set_index("sezione").loc["724"]
    assert not riga["scrutinata"]


def test_file_senza_intestazione():
    with pytest.raises(ErroreFormato):
        leggi_riepilogo(b"TITOLO\n1;2;3\n")


def test_gruppi_di_voti_mancanti():
    dati = (
        b'"Sezione";"Circoscrizione";"Totale iscritti";1;"A";2;"B"\n'
        b"1;1;100;;5\n"  # manca il voto di B
    )
    with pytest.raises(ErroreFormato):
        leggi_riepilogo(dati)
