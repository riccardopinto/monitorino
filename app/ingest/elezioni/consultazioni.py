"""Definizione delle consultazioni da caricare: file del Comune e loro contenuto.

Fonte: https://elezioni.comune.torino.it (Città di Torino), riepiloghi per sezione.
Ogni consultazione diventa una riga di ``elezione``; il primo turno e il ballottaggio delle
comunali sono due elezioni distinte, come i consigli circoscrizionali.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

BASE = "https://elezioni.comune.torino.it"


@dataclass(frozen=True)
class File:
    percorso: str  # sul sito del Comune
    tipo_soggetto: (
        str  # candidato_sindaco, candidato_presidente, candidato_uninominale, lista, preferenza
    )
    affluenza: bool = False  # il file fornisce iscritti, votanti e schede per la tabella affluenza
    membri: str | None = None  # per gli zip: espressione regolare dei file interni da leggere


@dataclass(frozen=True)
class Consultazione:
    chiave: str
    tipo: str  # comunali, circoscrizionali, camera, senato, europee, regionali
    data: date
    turno: int
    nome: str
    fonte: str  # cartella in data/raw
    file: tuple[File, ...] = field(default_factory=tuple)


def _f(percorso: str, tipo: str, affluenza: bool = False, membri: str | None = None) -> File:
    return File(percorso, tipo, affluenza, membri)


def _zip_circoscrizioni(anno_dir: str, liste: str, preferenze: str) -> tuple[File, ...]:
    out = []
    for n in range(1, 9):
        z = f"{anno_dir}/finali/circ{n}.zip"
        out.append(_f(z, "lista", affluenza=True, membri=liste.format(n=n)))
        out.append(_f(z, "preferenza", membri=preferenze.format(n=n)))
    return tuple(out)


EUROPEE_2024_PREF = [
    "lega_salvini_premier",
    "stati_uniti_deuropa",
    "pace_terra_dignita",
    "azione_siamo_europei",
    "alternativa_popolare",
    "liberta",
    "rassemblement_valdtain",
    "partito_democratico",
    "forza_italia_noi_moderati",
    "movimento_5_stelle",
    "alleanza_verdi_e_sinistra",
    "fratelli_ditalia",
]
REGIONALI_2024_PREF = [
    "liberta_piemonte",
    "piemonte_popolare",
    "movimento_5_stelle",
    "noi_moderati",
    "fratelli_ditalia",
    "lega_salvini_piemonte",
    "lista_civica_cirio_presidente",
    "forza_italia_ppe_udc_pli",
    "stati_uniti_deuropa_per_il_pi",
    "lista_civica_pentenero_preside",
    "lista_civica_piemonte_ambienta",
    "alleanza_verdi_e_sinistra",
    "partito_democratico",
]

CONSULTAZIONI: tuple[Consultazione, ...] = (
    Consultazione(
        "comunali_2016",
        "comunali",
        date(2016, 6, 5),
        1,
        "Comunali 2016 - 1° turno",
        "elezioni_comunali_2016",
        (
            _f("/2016/amministrative/finali/sindaco16_tt.csv", "candidato_sindaco", True),
            _f("/2016/amministrative/finali/co16_tt.csv", "lista"),
            *(
                _f(f"/2016/amministrative/finali/co16_tt_p{n:02d}.csv", "preferenza")
                for n in range(1, 35)
            ),
        ),
    ),
    Consultazione(
        "comunali_2016_ballottaggio",
        "comunali",
        date(2016, 6, 19),
        2,
        "Comunali 2016 - ballottaggio",
        "elezioni_comunali_2016",
        (
            _f(
                "/2016/amministrative/ballottaggio/finali/ballottaggiosindaco16_tt.csv",
                "candidato_sindaco",
                True,
            ),
        ),
    ),
    Consultazione(
        "circoscrizionali_2016",
        "circoscrizionali",
        date(2016, 6, 5),
        1,
        "Circoscrizionali 2016",
        "elezioni_comunali_2016",
        _zip_circoscrizioni(
            "/2016/amministrative", r"circ{n}/cs16_c0{n}\.csv", r"circ{n}/cs16_c0{n}_p\d+\.csv"
        ),
    ),
    Consultazione(
        "comunali_2021",
        "comunali",
        date(2021, 10, 3),
        1,
        "Comunali 2021 - 1° turno",
        "elezioni_comunali_2021",
        (
            _f("/2021/amministrative/finali/amministrative_sindaco.csv", "candidato_sindaco", True),
            _f("/2021/amministrative/finali/amministrative_liste.csv", "lista"),
            *(
                _f(f"/2021/amministrative/finali/preferenze_1_0_{n}.csv", "preferenza")
                for n in range(1, 31)
            ),
        ),
    ),
    Consultazione(
        "comunali_2021_ballottaggio",
        "comunali",
        date(2021, 10, 17),
        2,
        "Comunali 2021 - ballottaggio",
        "elezioni_comunali_2021",
        (
            _f(
                "/2021/amministrative/ballottaggio/finali/ballottaggiosindaco21.csv",
                "candidato_sindaco",
                True,
            ),
        ),
    ),
    Consultazione(
        "circoscrizionali_2021",
        "circoscrizionali",
        date(2021, 10, 3),
        1,
        "Circoscrizionali 2021",
        "elezioni_comunali_2021",
        _zip_circoscrizioni(
            "/2021/amministrative",
            r"circ{n}/liste_2_CIRC-{n}_{n}\.csv",
            r"circ{n}/preferenze_2_CIRC-{n}_{n}_\d+\.csv",
        ),
    ),
    Consultazione(
        "camera_2022",
        "camera",
        date(2022, 9, 25),
        1,
        "Camera 2022",
        "elezioni_politiche_2022",
        (
            _f("/2022/politiche/finali/camera_liste_collegio_1.csv", "lista", True),
            _f("/2022/politiche/finali/camera_liste_collegio_2.csv", "lista", True),
            _f("/2022/politiche/finali/camera_cand_uni_collegio_1.csv", "candidato_uninominale"),
            _f("/2022/politiche/finali/camera_cand_uni_collegio_2.csv", "candidato_uninominale"),
        ),
    ),
    Consultazione(
        "senato_2022",
        "senato",
        date(2022, 9, 25),
        1,
        "Senato 2022",
        "elezioni_politiche_2022",
        (
            _f("/2022/politiche/finali/senato_liste_collegio_1.csv", "lista", True),
            _f("/2022/politiche/finali/senato_cand_uni_collegio_1.csv", "candidato_uninominale"),
        ),
    ),
    Consultazione(
        "europee_2019",
        "europee",
        date(2019, 5, 26),
        1,
        "Europee 2019",
        "elezioni_europee_2019",
        (
            _f("/2019/europee/finali/liste.csv", "lista", True),
            *(
                _f(f"/2019/europee/finali/preferenze_lista_{n}.csv", "preferenza")
                for n in range(1, 17)
            ),
        ),
    ),
    Consultazione(
        "europee_2024",
        "europee",
        date(2024, 6, 9),
        1,
        "Europee 2024",
        "elezioni_europee_2024",
        (
            _f("/2024/europee/finali/liste.csv", "lista", True),
            *(_f(f"/2024/europee/finali/{n}.csv", "preferenza") for n in EUROPEE_2024_PREF),
        ),
    ),
    Consultazione(
        "regionali_2024",
        "regionali",
        date(2024, 6, 9),
        1,
        "Regionali 2024",
        "elezioni_regionali_2024",
        (
            _f("/2024/regionali/finali/cand_pres.csv", "candidato_presidente", True),
            _f("/2024/regionali/finali/liste.csv", "lista"),
            *(_f(f"/2024/regionali/finali/{n}.csv", "preferenza") for n in REGIONALI_2024_PREF),
        ),
    ),
)

PER_CHIAVE = {c.chiave: c for c in CONSULTAZIONI}
