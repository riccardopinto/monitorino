"""Aggregazione dei risultati del laboratorio messaggi.

Ogni persona sintetica pesa (peso dell'area) × (peso del segmento nell'area) / (persone del
segmento). I pesi dei segmenti vengono da segmento_peso, rinormalizzati sui segmenti del run;
le aree pesano per i residenti maggiorenni.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict

PAROLE_VUOTE = {
    "il",
    "lo",
    "la",
    "i",
    "gli",
    "le",
    "un",
    "uno",
    "una",
    "di",
    "a",
    "da",
    "in",
    "con",
    "su",
    "per",
    "tra",
    "fra",
    "e",
    "o",
    "ma",
    "che",
    "non",
    "più",
    "meno",
    "del",
    "dello",
    "della",
    "dei",
    "degli",
    "delle",
    "al",
    "allo",
    "alla",
    "ai",
    "agli",
    "alle",
    "dal",
    "dalla",
    "dai",
    "dalle",
    "nel",
    "nella",
    "nei",
    "nelle",
    "sul",
    "sulla",
    "sui",
    "sulle",
    "è",
    "sono",
    "essere",
    "troppo",
    "troppa",
    "molto",
    "poco",
    "come",
    "se",
    "si",
    "ci",
    "ne",
    "anche",
    "questo",
    "questa",
    "quello",
    "quella",
    "mio",
    "mia",
    "suo",
    "sua",
    "loro",
}
SOGLIA_SOMIGLIANZA = 0.5


def _parole(testo: str) -> set[str]:
    t = unicodedata.normalize("NFKD", testo.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    parole = re.findall(r"[a-z]+", t)
    # radice grossolana: senza vocale finale e al massimo 6 lettere (costi/costo, alti/alto)
    return {_radice(p) for p in parole if len(p) >= 4 and p not in PAROLE_VUOTE}


def _radice(parola: str) -> str:
    return (parola[:-1] if parola[-1] in "aeiou" else parola)[:6]


def raggruppa_obiezioni(timori: list[tuple[str, float]], massimo: int = 10) -> list[dict]:
    """Raggruppa timori simili (parole significative in comune, Jaccard ≥ 0,5).

    ``timori``: (testo, peso). Restituisce i gruppi ordinati per peso con l'etichetta più
    frequente, il peso totale e il numero di menzioni.
    """
    gruppi: list[dict] = []
    for testo, peso in timori:
        chiave = _parole(testo)
        if not chiave:
            continue
        migliore = None
        for g in gruppi:
            jac = len(chiave & g["parole"]) / len(chiave | g["parole"])
            if jac >= SOGLIA_SOMIGLIANZA and (migliore is None or jac > migliore[0]):
                migliore = (jac, g)
        if migliore:
            g = migliore[1]
            g["parole"] |= chiave
        else:
            g = {"parole": set(chiave), "testi": Counter(), "peso": 0.0, "menzioni": 0}
            gruppi.append(g)
        g["testi"][testo.strip()] += 1
        g["peso"] += peso
        g["menzioni"] += 1
    totale = sum(g["peso"] for g in gruppi) or 1
    out = [
        {
            "obiezione": g["testi"].most_common(1)[0][0],
            "varianti": [t for t, _ in g["testi"].most_common(4)[1:]],
            "menzioni": g["menzioni"],
            "quota_pct": round(g["peso"] / totale * 100, 1),
        }
        for g in gruppi
    ]
    return sorted(out, key=lambda x: -x["quota_pct"])[:massimo]


def _frase(area: str, indice: int, tipo: str, v: dict) -> dict:
    return {"area": area, "indice": indice, "tipo": tipo, "testo": v["reazione"],
            "gradimento": v["gradimento"]}  # fmt: skip


def _metriche(valutazioni: list[tuple[dict, float]]) -> dict:
    """Metriche pesate su (valutazione, peso)."""
    tot = sum(p for _, p in valutazioni)
    if tot <= 0:
        return {}
    media = sum(v["gradimento"] * p for v, p in valutazioni) / tot
    var = sum(p * (v["gradimento"] - media) ** 2 for v, p in valutazioni) / tot
    quote = {e: sum(p for v, p in valutazioni if v["effetto_voto"] == e) / tot * 100 for e in
             ("allontana", "nessuno", "avvicina")}  # fmt: skip
    favorevoli = sum(p for v, p in valutazioni if v["gradimento"] >= 4) / tot * 100
    return {
        "gradimento_medio": round(media, 2),
        "gradimento_dev": round(math.sqrt(var), 2),
        "allontana_pct": round(quote["allontana"], 1),
        "nessuno_pct": round(quote["nessuno"], 1),
        "avvicina_pct": round(quote["avvicina"], 1),
        "saldo": round(quote["avvicina"] - quote["allontana"], 1),
        "favorevoli_pct": round(favorevoli, 1),
        "n": len(valutazioni),
    }


def aggrega(
    segmenti: list[dict],
    pesi: dict[str, dict[int, float]],
    adulti: dict[str, float],
    risposte: dict[str, dict[int, list[dict]]],
    variante: str = "a",
) -> dict:
    """Aggregati di una variante ("a" o "b").

    ``risposte[circ][indice_segmento]`` = lista di risposte persona (dict con chiavi a, b).
    """
    aree = sorted(risposte, key=lambda c: int(c) if c.isdigit() else c)
    tot_adulti = sum(adulti.get(c, 0) for c in aree) or len(aree)
    peso_area = {c: (adulti.get(c, 0) or 1) / tot_adulti for c in aree}
    if not any(adulti.get(c) for c in aree):
        peso_area = {c: 1 / len(aree) for c in aree}

    righe_seg = []
    tutte: list[tuple[dict, float]] = []
    per_area: dict[str, list] = defaultdict(list)
    per_voto: dict[str, list] = defaultdict(list)
    timori: list[tuple[str, float]] = []
    parole: Counter = Counter()
    frasi = []
    for c in aree:
        for idx, persone in sorted(risposte[c].items()):
            vals = [p[variante] for p in persone if p.get(variante)]
            if not vals:
                continue
            w_seg = pesi.get(c, {}).get(idx, 0.0)
            w_persona = peso_area[c] * w_seg / len(vals)
            m = _metriche([(v, 1.0) for v in vals])
            seg = segmenti[idx]
            righe_seg.append({"area": c, "indice": idx, **seg, "peso": round(w_seg, 4), **m})
            for v in vals:
                tutte.append((v, w_persona))
                per_area[c].append((v, w_seg / len(vals)))
                per_voto[seg["area_di_voto"]].append((v, w_persona))
                for t in v.get("timori", []):
                    timori.append((t, w_persona))
                for parola in v.get("parole_ricordate", []):
                    parole[parola.strip().lower()] += 1
            ordinate = sorted(vals, key=lambda v: abs(v["gradimento"] - m["gradimento_medio"]))
            frasi.append(_frase(c, idx, "tipica", ordinate[0]))
            alta = max(vals, key=lambda v: v["gradimento"])
            bassa = min(vals, key=lambda v: v["gradimento"])
            if alta["gradimento"] != bassa["gradimento"]:
                frasi.append(_frase(c, idx, "favorevole", alta))
                frasi.append(_frase(c, idx, "contraria", bassa))
    return {
        "totale": _metriche(tutte),
        "aree": [
            {"area": c, "peso": round(peso_area[c], 4), **_metriche(per_area[c])} for c in aree
        ],
        "aree_di_voto": [{"area_di_voto": k, **_metriche(v)} for k, v in sorted(per_voto.items())],
        "segmenti": righe_seg,
        "obiezioni": raggruppa_obiezioni(timori),
        "parole_ricordate": [{"parola": p, "volte": n} for p, n in parole.most_common(10)],
        "frasi": frasi,
    }


def confronto_ab(a: dict, b: dict) -> dict:
    """Differenze B − A su totale, aree e segmenti (stesso panel: disegno appaiato)."""

    def delta(x: dict, y: dict) -> dict:
        return {
            k: round(y[k] - x[k], 2)
            for k in ("gradimento_medio", "saldo", "favorevoli_pct")
            if k in x and k in y
        }

    return {
        "totale": delta(a["totale"], b["totale"]),
        "aree": [
            {"area": x["area"], **delta(x, y)} for x, y in zip(a["aree"], b["aree"], strict=True)
        ],
        "segmenti": [
            {"area": x["area"], "indice": x["indice"], **delta(x, y)}
            for x, y in zip(a["segmenti"], b["segmenti"], strict=True)
        ],
    }


def testo_per_sintesi(
    proposta: str, proposta_b: str | None, aggregati: dict, segmenti: list[dict]
) -> str:
    """Riassunto numerico (solo aggregati) da dare al modello di sintesi."""

    def blocco(nome: str, ag: dict) -> str:
        t = ag["totale"]
        righe = [
            f"[{nome}] Totale: gradimento medio {t['gradimento_medio']} "
            f"(dev. {t['gradimento_dev']}), "
            f"favorevoli {t['favorevoli_pct']}%, avvicina {t['avvicina_pct']}%, allontana "
            f"{t['allontana_pct']}%, saldo {t['saldo']:+} punti."
        ]
        for a in ag["aree_di_voto"]:
            righe.append(
                f"  area di voto {a['area_di_voto']}: gradimento {a['gradimento_medio']}, "
                f"saldo {a['saldo']:+}"
            )
        for s in ag["segmenti"]:
            righe.append(
                f"  circ. {s['area']}, {s['fascia_eta']} {s['condizione']} {s['area_di_voto']} "
                f"(peso {s['peso']}): gradimento {s['gradimento_medio']}, saldo {s['saldo']:+}"
            )
        righe.append(
            "  Obiezioni principali: "
            + "; ".join(f"{o['obiezione']} ({o['quota_pct']}%)" for o in ag["obiezioni"][:6])
        )
        return "\n".join(righe)

    parti = [f"Proposta A: {proposta}"]
    if proposta_b:
        parti.append(f"Proposta B: {proposta_b}")
    parti.append(blocco("A", aggregati["a"]))
    if aggregati.get("b"):
        parti.append(blocco("B", aggregati["b"]))
    return "\n\n".join(parti)
