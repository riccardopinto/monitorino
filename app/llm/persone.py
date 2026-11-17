"""Panel di persone sintetiche, generato in modo deterministico dal seed.

Ogni persona ha sesso, età, quartiere e due tratti: servono a rendere concrete e diverse le
risposte del modello, non a descrivere persone reali. Stesso seed, segmento e area danno
sempre lo stesso panel (random.Random con seme testuale, deterministico tra esecuzioni).
"""

from __future__ import annotations

import random
import re
from dataclasses import asdict, dataclass

import pandas as pd

# Gruppi di tratti mutuamente esclusivi: da ogni gruppo al massimo uno.
TRATTI = [
    ["ha figli piccoli", "ha figli adolescenti", "non ha figli"],
    ["usa i mezzi pubblici ogni giorno", "si sposta soprattutto in auto", "va in bici"],
    ["vive in affitto", "vive in una casa di proprietà", "vive in una casa popolare",
     "vive con i genitori"],
    ["ha un'attività o lavora nel quartiere", "lavora fuori Torino"],
    ["fa volontariato nel quartiere", "frequenta la parrocchia", "frequenta il circolo sportivo"],
    ["segue poco la politica", "è molto informato sulla politica locale"],
    ["assiste un genitore anziano", "porta il cane ai giardini", "va al mercato rionale"],
]  # fmt: skip
LAVORATORI = ("lavoratore dipendente", "lavoratore autonomo")
# Tratti ammessi solo per certe età o condizioni, per non creare profili inverosimili.
VINCOLI = {
    "ha figli piccoli": lambda eta, cond: 22 <= eta <= 50 and cond != "studente",
    "ha figli adolescenti": lambda eta, cond: 35 <= eta <= 62,
    "vive con i genitori": lambda eta, cond: eta <= 34,
    "ha un'attività o lavora nel quartiere": lambda eta, cond: cond in LAVORATORI,
    "lavora fuori Torino": lambda eta, cond: cond in LAVORATORI,
    "assiste un genitore anziano": lambda eta, cond: 35 <= eta <= 75,
}
ETA_MAX = 95


@dataclass(frozen=True)
class PersonaSintetica:
    codice: str  # P01, P02, ... unico nel segmento
    sesso: str  # donna | uomo
    eta: int
    quartiere: str
    tratti: tuple[str, ...]

    def descrizione(self) -> str:
        tratti = ", ".join(self.tratti)
        return f"{self.codice}: {self.sesso}, {self.eta} anni, {self.quartiere}; {tratti}"

    def come_dict(self) -> dict:
        d = asdict(self)
        d["tratti"] = list(self.tratti)
        return d


def _fascia(fascia: str) -> tuple[int, int]:
    if fascia.endswith("+"):
        return int(fascia[:-1]), ETA_MAX
    da, a = fascia.split("-")
    return int(da), int(a)


def quartieri(nome_circoscrizione: str) -> list[str]:
    return [q.strip() for q in re.split(r"[,\-]", nome_circoscrizione) if q.strip()]


def genera_panel(
    seed: int,
    segmento: dict[str, str],
    circoscrizione: str,
    n: int,
    pop_maschi: pd.Series,
    pop_femmine: pd.Series,
    nome_circoscrizione: str,
) -> list[PersonaSintetica]:
    """Panel di ``n`` persone per un segmento e una circoscrizione.

    ``pop_maschi`` e ``pop_femmine``: residenti per età singola della circoscrizione
    (indice = età). Età e sesso si estraggono con queste quote dentro la fascia del segmento.
    """
    parti = (segmento["fascia_eta"], segmento["condizione"], segmento["area_di_voto"])
    chiave = "|".join((str(seed), circoscrizione, *parti))
    rng = random.Random(chiave)
    da, a = _fascia(segmento["fascia_eta"])
    eta = list(range(da, a + 1))
    pesi_m = [float(pop_maschi.get(e, 0)) for e in eta]
    pesi_f = [float(pop_femmine.get(e, 0)) for e in eta]
    if sum(pesi_m) + sum(pesi_f) == 0:
        pesi_m = pesi_f = [1.0] * len(eta)
    quota_f = sum(pesi_f) / (sum(pesi_m) + sum(pesi_f))
    nomi_quartieri = quartieri(nome_circoscrizione) or [f"circoscrizione {circoscrizione}"]
    panel = []
    for i in range(n):
        donna = rng.random() < quota_f
        pesi = pesi_f if donna else pesi_m
        eta_p = rng.choices(eta, weights=pesi if sum(pesi) else None)[0]
        panel.append(
            PersonaSintetica(
                codice=f"P{i + 1:02d}",
                sesso="donna" if donna else "uomo",
                eta=eta_p,
                quartiere=rng.choice(nomi_quartieri),
                tratti=_tratti(rng, eta_p, segmento["condizione"]),
            )
        )
    return panel


def compatibile(tratto: str, eta: int, condizione: str) -> bool:
    vincolo = VINCOLI.get(tratto)
    return vincolo is None or vincolo(eta, condizione)


def _tratti(rng: random.Random, eta: int, condizione: str, quanti: int = 2) -> tuple[str, ...]:
    """Due tratti da gruppi diversi, compatibili con età e condizione."""
    scelti = []
    for gruppo in rng.sample(TRATTI, len(TRATTI)):
        ammessi = [t for t in gruppo if compatibile(t, eta, condizione)]
        if ammessi:
            scelti.append(rng.choice(ammessi))
        if len(scelti) == quanti:
            break
    return tuple(scelti)
