"""Dati dei report: una funzione per tipo, che restituisce il contesto del template.

Riusa le stesse funzioni della dashboard (analisi e router, che sono funzioni normali), così
report e interfaccia mostrano sempre gli stessi numeri.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from app.analysis import calibrazione as cal
from app.analysis import elezioni as an
from app.api import demografia as api_dem
from app.api import elezioni as api_el
from app.api import temi as api_temi
from app.core import db
from app.core.config import elenco_candidati
from app.llm import prompt_simulazione as ps
from app.llm import simulazione as sim
from app.reports import fonti, grafici, mappe
from app.reports.genera import data_it, num, segno

TIPI = {
    "scheda": "Scheda circoscrizione",
    "confronto": "Confronto",
    "bollettino": "Bollettino settimanale dei temi",
    "simulazione": "Report di simulazione",
    "kit": "Kit messaggi",
}
AREE_POLITICHE = ["centrosinistra", "centrodestra", "M5S", "civici e terzo polo", "altro"]
COLORI_AREE = {"centrosinistra": "#d6604d", "centrodestra": "#2166ac", "M5S": "#eda100",
               "civici e terzo polo": "#1baf7a", "altro": "#9aa1ab"}  # fmt: skip
SETTIMANE_TEMI = 4


class ErroreDati(ValueError):
    pass


# --- comuni -------------------------------------------------------------------


def _nomi_circ(con) -> dict[str, str]:
    return dict(
        con.execute("SELECT codice, nome FROM area WHERE tipo = 'circoscrizione'").fetchall()
    )


def _circ(con, codice: str | None) -> str:
    nomi = _nomi_circ(con)
    if codice not in nomi:
        raise ErroreDati(f"Circoscrizione {codice!r} non trovata")
    return codice


def _elezioni(con, solo_primo_turno: bool = True) -> list[dict]:
    filtro = "WHERE turno = 1" if solo_primo_turno else ""
    righe = con.execute(
        f"SELECT id, nome, tipo, data, turno FROM elezione {filtro} ORDER BY data, tipo"
    ).fetchall()
    return [{"id": i, "nome": n, "tipo": t, "data": d, "turno": tu} for i, n, t, d, tu in righe]


def _elezione(con, eid) -> dict:
    for e in _elezioni(con, solo_primo_turno=False):
        if e["id"] == eid:
            return e
    raise ErroreDati(f"Elezione {eid} non trovata")


def _quote_aree(con, eid: int, livello: str, codice: str) -> dict[str, float]:
    r = an.risultati(con, eid, livello, "area")
    r = r[r.area == codice]
    return {s: round(float(q) * 100, 2) for s, q in zip(r.soggetto, r.quota, strict=True)}


def _affluenza(con, eid: int, livello: str, codice: str) -> float | None:
    a = an.affluenza(con, eid, livello).set_index("area")["affluenza"]
    return round(float(a[codice]) * 100, 2) if codice in a.index else None


def _demografia(con, codice: str) -> dict | None:
    try:
        return api_dem.scheda(con, "circoscrizione", codice)
    except HTTPException:
        return None


def comune(con, tipo: str, *, titolo: str, sottotitolo: str, autore: str, versione: str) -> dict:
    ora = datetime.now()
    return {
        "tipo": tipo,
        "etichetta_tipo": TIPI[tipo],
        "titolo": titolo,
        "sottotitolo": sottotitolo,
        "autore": autore,
        "versione": versione,
        "generato_il": ora.date(),
        "ora": f"{ora:%H:%M}",
        "dati_di_prova": db.dati_di_prova(con),
        "fonti": fonti.elenco(con, fonti.PER_REPORT[tipo]),
        "dicitura": None,
        "grafici": [],
        "aree_politiche": AREE_POLITICHE,
    }


# --- scheda circoscrizione ----------------------------------------------------


def scheda(con, p: dict, **meta) -> dict:
    codice = _circ(con, p.get("area"))
    nome = _nomi_circ(con)[codice]
    ctx = comune(con, "scheda", titolo=meta.pop("titolo", None) or f"Circoscrizione {codice}",
                 sottotitolo=nome, **meta)  # fmt: skip
    ctx["codice"], ctx["nome"] = codice, nome
    ctx["mappa"] = mappe.evidenzia(con, codice)

    dem = _demografia(con, codice)
    ctx["demografia"] = dem
    if dem and dem.get("piramide"):
        ctx["grafici"].append(grafici.piramide("g-piramide", dem["piramide"]))

    storico = []
    for e in _elezioni(con):
        quote = _quote_aree(con, e["id"], "circoscrizione", codice)
        if not quote:
            continue
        storico.append({
            **e, "quote": quote, "quote_citta": _quote_aree(con, e["id"], "citta", "Torino"),
            "affluenza": _affluenza(con, e["id"], "circoscrizione", codice),
            "affluenza_citta": _affluenza(con, e["id"], "citta", "Torino"),
        })  # fmt: skip
    ctx["storico"] = storico
    if storico:
        etichette = [e["nome"] for e in storico]
        ctx["grafici"].append(grafici.linee("g-affluenza", etichette, [
            {"nome": f"Circoscrizione {codice}", "valori": [e["affluenza"] for e in storico],
             "colore": grafici.AREA},
            {"nome": "Torino", "valori": [e["affluenza_citta"] for e in storico],
             "colore": "#8a94a6"},
        ], "affluenza %"))  # fmt: skip
        ultima = next((e for e in reversed(storico) if e["tipo"] == "comunali"), storico[-1])
        ctx["ultima"] = ultima
        ctx["grafici"].append(grafici.barre("g-ultima", AREE_POLITICHE, [
            {"nome": f"Circoscrizione {codice}", "colore": grafici.AREA,
             "valori": [ultima["quote"].get(a, 0) for a in AREE_POLITICHE]},
            {"nome": "Torino", "colore": grafici.CITTA,
             "valori": [ultima["quote_citta"].get(a, 0) for a in AREE_POLITICHE]},
        ], titolo_valori="% dei voti di lista"))  # fmt: skip

    m = api_temi.matrice(con, settimane=SETTIMANE_TEMI)
    celle = sorted((c for c in m["celle"] if c["area"] == codice), key=lambda c: -c["volume"])
    nov = api_temi.novita(con, date.fromisoformat(m["dal"]), api_temi._dal(1)).get(codice, {})
    ctx["temi"] = {"dal": m["dal"], "celle": celle[:10], "nuovi": nov.get("nuovi", [])}
    return ctx


# --- confronto ----------------------------------------------------------------


def confronto(con, p: dict, **meta) -> dict:
    modo = p.get("modo", "elezioni")
    if modo == "elezioni":
        return _confronto_elezioni(con, p, **meta)
    if modo == "aree":
        return _confronto_aree(con, p, **meta)
    raise ErroreDati(f"Modalità di confronto non prevista: {modo}")


def _confronto_elezioni(con, p: dict, **meta) -> dict:
    da, a = _elezione(con, p.get("da")), _elezione(con, p.get("a"))
    area = p.get("area") or "Torino"
    livello = "citta" if area == "Torino" else "circoscrizione"
    if livello == "circoscrizione":
        _circ(con, area)
    nome_area = "Torino" if area == "Torino" else f"Circoscrizione {area}"
    ctx = comune(con, "confronto",
                 titolo=meta.pop("titolo", None) or f"{da['nome']} e {a['nome']}",
                 sottotitolo=f"{nome_area} · confronto tra elezioni", **meta)  # fmt: skip
    ctx.update(modo="elezioni", da=da, a=a, area=area, nome_area=nome_area)
    q_da = _quote_aree(con, da["id"], livello, area)
    q_a = _quote_aree(con, a["id"], livello, area)
    righe = [{"soggetto": s, "da": q_da.get(s, 0.0), "a": q_a.get(s, 0.0),
              "variazione": round(q_a.get(s, 0.0) - q_da.get(s, 0.0), 2)}
             for s in AREE_POLITICHE if s in q_da or s in q_a]  # fmt: skip
    ctx["righe"] = righe
    ctx["affluenza"] = {"da": _affluenza(con, da["id"], livello, area),
                        "a": _affluenza(con, a["id"], livello, area)}  # fmt: skip
    ctx["grafici"].append(grafici.barre("g-quote", [r["soggetto"] for r in righe], [
        {"nome": da["nome"], "colore": grafici.CITTA, "valori": [r["da"] for r in righe]},
        {"nome": a["nome"], "colore": grafici.AREA, "valori": [r["a"] for r in righe]},
    ], titolo_valori="% dei voti di lista"))  # fmt: skip

    soggetto = p.get("soggetto") or max(righe, key=lambda r: abs(r["variazione"]))["soggetto"]
    var = an.variazione(con, da["id"], a["id"], "circoscrizione", "area")
    var = var[var.soggetto == soggetto]
    valori = {r.area: round(float(r.variazione_punti), 2) for r in var.itertuples() if r.area}
    ctx["soggetto_mappa"] = soggetto
    ctx["variazioni_circ"] = sorted(valori.items(), key=lambda kv: int(kv[0]))
    ctx["mappa"] = mappe.coropletica(con, valori, divergente=True,
                                     formato=lambda v: segno(v) + " punti",
                                     titolo=f"Variazione {soggetto}")  # fmt: skip
    try:
        f = api_el.flussi(con, da["id"], a["id"], None if area == "Torino" else area)
        ctx["flussi"] = f
    except HTTPException as e:
        ctx["flussi"] = None
        ctx["errore_flussi"] = str(e.detail)
    return ctx


def _confronto_aree(con, p: dict, **meta) -> dict:
    e = _elezione(con, p.get("elezione"))
    a1, a2 = _circ(con, p.get("area1")), _circ(con, p.get("area2"))
    if a1 == a2:
        raise ErroreDati("Scegliere due circoscrizioni diverse")
    nomi = _nomi_circ(con)
    ctx = comune(con, "confronto",
                 titolo=meta.pop("titolo", None) or f"Circoscrizioni {a1} e {a2}",
                 sottotitolo=f"{e['nome']} · confronto tra aree", **meta)  # fmt: skip
    ctx.update(modo="aree", elezione=e, area1=a1, area2=a2, nome1=nomi[a1], nome2=nomi[a2])
    q1 = _quote_aree(con, e["id"], "circoscrizione", a1)
    q2 = _quote_aree(con, e["id"], "circoscrizione", a2)
    qc = _quote_aree(con, e["id"], "citta", "Torino")
    righe = [{"soggetto": s, "a1": q1.get(s, 0.0), "a2": q2.get(s, 0.0), "citta": qc.get(s, 0.0)}
             for s in AREE_POLITICHE if s in q1 or s in q2]  # fmt: skip
    ctx["righe"] = righe
    ctx["affluenza"] = {"a1": _affluenza(con, e["id"], "circoscrizione", a1),
                        "a2": _affluenza(con, e["id"], "circoscrizione", a2),
                        "citta": _affluenza(con, e["id"], "citta", "Torino")}  # fmt: skip
    ctx["grafici"].append(grafici.barre("g-quote", [r["soggetto"] for r in righe], [
        {"nome": f"Circoscrizione {a1}", "colore": grafici.SERIE[0],
         "valori": [r["a1"] for r in righe]},
        {"nome": f"Circoscrizione {a2}", "colore": grafici.SERIE[1],
         "valori": [r["a2"] for r in righe]},
        {"nome": "Torino", "colore": grafici.CITTA, "valori": [r["citta"] for r in righe]},
    ], titolo_valori="% dei voti di lista"))  # fmt: skip
    d1, d2 = _demografia(con, a1), _demografia(con, a2)
    indicatori = []
    if d1 and d2:
        per_chiave = {r["chiave"]: r for r in d2["indicatori"]}
        for r in d1["indicatori"]:
            r2 = per_chiave.get(r["chiave"], {})
            indicatori.append({**r, "valore2": r2.get("valore")})
    ctx["indicatori"] = indicatori
    ctx["mappa"] = mappe.evidenzia(con, {a1: grafici.SERIE[0], a2: grafici.SERIE[1]})
    return ctx


# --- bollettino dei temi --------------------------------------------------------


def bollettino(con, p: dict, **meta) -> dict:
    if p.get("settimana"):
        sett = date.fromisoformat(p["settimana"])
        sett -= timedelta(days=sett.weekday())
    else:
        (ultima,) = con.execute("SELECT max(settimana) FROM tema_aggregato").fetchone()
        sett = ultima or api_temi._dal(1)
    fine = sett + timedelta(days=6)
    ctx = comune(con, "bollettino",
                 titolo=meta.pop("titolo", None) or f"Temi della settimana {data_it(sett)}",
                 sottotitolo=f"dal {data_it(sett)} al {data_it(fine)}", **meta)  # fmt: skip
    ctx.update(settimana=sett, fine=fine)
    nascosti = api_temi.NON_ESCLUSO
    citta = con.execute(
        f"SELECT tema, volume, sentiment_medio, n_fonti FROM tema_aggregato t "
        f"WHERE settimana = ? AND area_id IS NULL AND {nascosti} ORDER BY volume DESC",
        [sett],
    ).fetchall()
    ctx["citta"] = [{"tema": t, "volume": v, "sentiment": s, "n_fonti": n} for t, v, s, n in citta]
    celle = con.execute(
        f"SELECT t.tema, a.codice, t.volume FROM tema_aggregato t JOIN area a ON a.id = t.area_id "
        f"WHERE t.settimana = ? AND a.tipo = 'circoscrizione' AND {nascosti}",
        [sett],
    ).fetchall()
    matrice = {}
    for tema, codice, v in celle:
        matrice.setdefault(tema, {})[codice] = v
    ctx["circoscrizioni"] = [str(i) for i in range(1, 9)]
    ctx["matrice"] = [
        {"tema": r["tema"], "celle": matrice.get(r["tema"], {})} for r in ctx["citta"]
    ]
    massimo = max((v for _, _, v in celle), default=0)
    limiti, colori = mappe.classi([0, massimo], False) if massimo else ([], [])
    ctx["colore_cella"] = lambda v: mappe.colore_di(limiti, colori, v) if v and colori else ""
    ctx["cella_scura"] = lambda v: (
        bool(v and colori)
        and mappe.colore_di(limiti, colori, v) in mappe.SEQUENZIALE[mappe.PRIMO_SCURO :]
    )
    ctx["nuovi"] = api_temi.novita(con, sett, sett)
    ctx["esclusi"] = api_temi.esclusi(con)

    if ctx["citta"]:
        principale = ctx["citta"][0]["tema"]
        ctx["principale"] = principale
        valori = {k: float(v) for k, v in matrice.get(principale, {}).items()}
        ctx["mappa"] = mappe.coropletica(con, valori, formato=lambda v: f"{v:.0f} documenti",
                                         titolo=principale)  # fmt: skip
        inizio = sett - timedelta(weeks=7)
        settimane = [inizio + timedelta(weeks=i) for i in range(8)]
        primi = [r["tema"] for r in ctx["citta"][:5]]
        serie = con.execute(
            "SELECT tema, settimana, volume FROM tema_aggregato "
            "WHERE area_id IS NULL AND settimana BETWEEN ? AND ?",
            [inizio, sett],
        ).fetchall()
        per_tema = {t: [0] * 8 for t in primi}
        for t, s, v in serie:
            if t in per_tema:
                per_tema[t][(s - inizio).days // 7] = v
        ctx["grafici"].append(grafici.linee(
            "g-andamento", [f"{s.day}/{s.month}" for s in settimane],
            [{"nome": t, "valori": per_tema[t], "colore": grafici.SERIE[i]}
             for i, t in enumerate(primi)], "documenti"))  # fmt: skip

    articoli = con.execute(
        "SELECT titolo, fonte, data, url, tema FROM documento "
        "WHERE tipo_fonte IN ('news', 'istituzionale') AND coalesce(pertinente, true) "
        "AND tema IS NOT NULL AND data BETWEEN ? AND ? "
        "AND tema NOT IN (SELECT tema FROM tema_escluso) ORDER BY tema, data DESC LIMIT 60",
        [sett, fine],
    ).fetchall()
    ctx["articoli"] = [{"titolo": t, "testata": f, "data": d, "url": u, "tema": te}
                       for t, f, d, u, te in articoli]  # fmt: skip
    social = con.execute(
        "SELECT tema, count(*) FROM documento WHERE tipo_fonte = 'social' AND tema IS NOT NULL "
        "AND coalesce(pertinente, true) AND data BETWEEN ? AND ? GROUP BY 1 ORDER BY 2 DESC",
        [sett, fine],
    ).fetchall()
    ctx["social"] = [{"tema": t, "n": n} for t, n in social]
    return ctx


# --- simulazione ----------------------------------------------------------------


def simulazione(con, p: dict, **meta) -> dict:
    try:
        run = sim.carica(con, int(p.get("simulazione")))
    except (sim.ErroreSimulazione, TypeError, ValueError) as e:
        raise ErroreDati(f"Simulazione non trovata: {p.get('simulazione')}") from e
    if "aggregati" not in run["risultati"]:
        raise ErroreDati("La simulazione non è ancora completa: importare tutte le risposte")
    par = run["parametri"]
    ctx = comune(con, "simulazione",
                 titolo=meta.pop("titolo", None) or f"Simulazione {run['id']}",
                 sottotitolo=run["proposta"], **meta)  # fmt: skip
    ctx["dicitura"] = ps.DICITURA
    ctx["limiti"] = list(ps.LIMITI)
    ctx["run"] = run
    ctx["par"] = par
    ctx["nomi_circ"] = _nomi_circ(con)
    ag = run["risultati"]["aggregati"]
    ctx["ag"] = ag
    ctx["sintesi"] = run["risultati"].get("sintesi")
    ctx["affidabilita"] = cal.affidabilita(con)
    ctx["calibrazioni"] = cal.elenco(con, run["id"])
    varianti = ["a", "b"] if "b" in ag else ["a"]
    ctx["varianti"] = varianti
    for v in varianti:
        a = ag[v]
        ctx["grafici"].append(grafici.divergenti(
            f"g-voto-{v}", [r["area_di_voto"] for r in a["aree_di_voto"]],
            [r["saldo"] for r in a["aree_di_voto"]]))  # fmt: skip
        for area in run["aree"]:
            segs = [s for s in a["segmenti"] if s["area"] == area]
            ctx["grafici"].append(grafici.divergenti(
                f"g-seg-{v}-{area}",
                [f"{s['fascia_eta']} · {s['condizione']} · {s['area_di_voto']}" for s in segs],
                [s["saldo"] for s in segs]))  # fmt: skip
    if len(run["aree"]) > 1:
        valori = {r["area"]: r["saldo"] for r in ag["a"]["aree"]}
        ctx["mappa"] = mappe.coropletica(
            con, valori, divergente=True, formato=lambda v: segno(v) + " punti",
            titolo="Saldo netto per circoscrizione (versione A)",
        )  # fmt: skip
    return ctx


# --- kit messaggi -----------------------------------------------------------------


def kit(con, p: dict, **meta) -> dict:
    chiave = p.get("candidato")
    candidati = dict(elenco_candidati())
    if chiave not in candidati:
        raise ErroreDati(f"Candidato {chiave!r} non trovato in config/candidati.yaml")
    c = candidati[chiave]
    oggi = date.today()
    dal = date.fromisoformat(p["dal"]) if p.get("dal") else oggi - timedelta(days=30)
    al = date.fromisoformat(p["al"]) if p.get("al") else oggi
    if dal > al:
        raise ErroreDati("La data di inizio è successiva a quella di fine")
    ctx = comune(con, "kit", titolo=meta.pop("titolo", None) or f"Kit messaggi · {c.nome}",
                 sottotitolo=f"Contenuti approvati dal {data_it(dal)} al {data_it(al)}",
                 **meta)  # fmt: skip
    ctx.update(candidato=c, dal=dal, al=al)
    righe = con.execute(
        "SELECT id, formato, canale, testo, fonti_dati, autore, timestamp FROM contenuto "
        "WHERE stato = 'approvato' AND candidato IN (?, ?) "
        "AND CAST(timestamp AS DATE) BETWEEN ? AND ? ORDER BY formato, timestamp DESC",
        [chiave, c.nome, dal, al],
    ).fetchall()
    gruppi: dict[str, list] = {}
    for id_, formato, canale, testo, fonti_dati, autore, ts in righe:
        elenco_fonti = json.loads(fonti_dati) if isinstance(fonti_dati, str) else (fonti_dati or [])
        gruppi.setdefault(formato, []).append({
            "id": id_, "canale": canale, "testo": testo, "autore": autore, "data": ts.date(),
            "fonti": [f if isinstance(f, str) else json.dumps(f, ensure_ascii=False)
                      for f in elenco_fonti],
        })  # fmt: skip
    ctx["gruppi"] = gruppi
    ctx["n"] = len(righe)
    return ctx


COSTRUTTORI = {
    "scheda": scheda,
    "confronto": confronto,
    "bollettino": bollettino,
    "simulazione": simulazione,
    "kit": kit,
}


def contesto(con, tipo: str, parametri: dict, *, autore: str = "", titolo: str = "",
             versione: str = "") -> dict:  # fmt: skip
    if tipo not in COSTRUTTORI:
        raise ErroreDati(f"Tipo di report non previsto: {tipo}")
    return COSTRUTTORI[tipo](con, parametri, autore=autore, titolo=titolo or None,
                             versione=versione)  # fmt: skip


__all__ = ["TIPI", "ErroreDati", "contesto", "num", "segno"]
