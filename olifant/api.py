"""Le serveur : il sert ce que `calcule` a produit, et recueille ce qu'on
rapporte de la balade.

Il ne calcule aucune trace et n'appelle aucun routeur. Tout ce qui coute du
reseau se fait avant, en ligne de commande ; le serveur ne fait que distribuer
des fichiers deja ecrits. Consequence voulue : si le NAS tombe, les GPX deja
telecharges continuent d'exister sur le telephone, et remettre le service
debout ne demande aucun appel a un service exterieur.

Ce qu'il ajoute, en revanche, ne peut pas etre un fichier fige : les notes de
sortie et les traces reellement suivies, qui arrivent apres coup et vivent
dans un volume qu'on sauvegarde.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import asynccontextmanager, closing
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

RACINE = Path(__file__).resolve().parent.parent
WEB = Path(__file__).resolve().parent / "web"

# Deux dossiers, et la difference compte pour le deploiement : SORTIE contient
# ce que le calcul a produit et voyage avec l'image ; ECRITURE contient ce qui
# nait de l'usage -- le carnet et les traces suivies -- et doit survivre a une
# mise a jour, donc vivre dans un volume qu'on sauvegarde.
SORTIE = Path(os.environ.get("OLIFANT_SORTIE", RACINE / "data" / "sortie"))
ECRITURE = Path(os.environ.get("OLIFANT_DATA", RACINE / "data"))
TRACES = ECRITURE / "traces"
BASE = ECRITURE / "carnet.db"

TAILLE_MAX = 20 * 1024 * 1024      # un GPX de journee pese quelques centaines de ko

# ---------------------------------------------------------------- carnet

def connexion() -> sqlite3.Connection:
    BASE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(BASE)
    conn.row_factory = sqlite3.Row
    return conn


def prepare_base() -> None:
    with closing(connexion()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sortie (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                parcours_id TEXT NOT NULL,
                jour        TEXT NOT NULL,
                km          REAL,
                minutes     INTEGER,
                temps       TEXT,
                chemins     TEXT,
                ressenti    TEXT,
                mot         TEXT,
                trace       TEXT,
                ecrit_le    TEXT NOT NULL DEFAULT (datetime('now'))
            )""")
        conn.commit()



@asynccontextmanager
async def demarrage(_: FastAPI):
    prepare_base()
    TRACES.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Olifant", docs_url="/api/docs", lifespan=demarrage)
# Leaflet est servi par le NAS, pas par un CDN : le site marche meme si
# unpkg tombe, et rien de la page ne part chez un tiers.
app.mount("/vendor", StaticFiles(directory=WEB / "vendor"), name="vendor")


# ---------------------------------------------------------------- lecture

def _catalogue() -> dict:
    fichier = SORTIE / "parcours.json"
    if not fichier.exists():
        raise HTTPException(
            503, "Rien n'a encore ete calcule. Lancez `python -m olifant calcule`.")
    return json.loads(fichier.read_text(encoding="utf-8"))


@app.get("/", response_class=HTMLResponse)
def page() -> HTMLResponse:
    return HTMLResponse((WEB / "index.html").read_text(encoding="utf-8"))


@app.get("/api/parcours")
def parcours() -> JSONResponse:
    """Le catalogue mesure, enrichi du nombre de fois qu'on a fait chaque boucle."""
    catalogue = _catalogue()
    with closing(connexion()) as conn:
        comptes = {r["parcours_id"]: r["n"] for r in conn.execute(
            "SELECT parcours_id, COUNT(*) AS n FROM sortie GROUP BY parcours_id")}
    for p in catalogue["parcours"]:
        p["fois"] = comptes.get(p["id"], 0)
    return JSONResponse(catalogue)


@app.get("/api/traces.geojson")
def traces() -> FileResponse:
    return _fichier(SORTIE / "traces.geojson", "application/geo+json")


@app.get("/telecharge/{parcours_id}.{extension}")
def telecharge(parcours_id: str, extension: str) -> FileResponse:
    if extension not in ("gpx", "kml"):
        raise HTTPException(404, "On ne sert que du gpx et du kml")
    types = {"gpx": "application/gpx+xml", "kml": "application/vnd.google-earth.kml+xml"}
    return _fichier(SORTIE / ("%s.%s" % (parcours_id, extension)), types[extension],
                    telechargement=True)


def _fichier(chemin: Path, type_mime: str, telechargement: bool = False) -> FileResponse:
    # Le nom vient de l'URL : on verifie qu'on ne sort pas du dossier servi.
    if not chemin.resolve().is_relative_to(SORTIE.resolve()) or not chemin.exists():
        raise HTTPException(404, "Ce fichier n'existe pas ; a-t-on lance le calcul ?")
    return FileResponse(chemin, media_type=type_mime,
                        filename=chemin.name if telechargement else None)


# ---------------------------------------------------------------- ecriture

@app.get("/api/sorties")
def sorties() -> JSONResponse:
    with closing(connexion()) as conn:
        lignes = conn.execute(
            "SELECT * FROM sortie ORDER BY jour DESC, id DESC").fetchall()
    return JSONResponse([dict(l) for l in lignes])


@app.post("/api/sorties")
def note_une_sortie(
    parcours_id: Annotated[str, Form()],
    jour: Annotated[str, Form()] = "",
    km: Annotated[float | None, Form()] = None,
    minutes: Annotated[int | None, Form()] = None,
    temps: Annotated[str, Form()] = "",
    chemins: Annotated[str, Form()] = "",
    ressenti: Annotated[str, Form()] = "",
    mot: Annotated[str, Form()] = "",
) -> JSONResponse:
    connus = {p["id"] for p in _catalogue()["parcours"]}
    if parcours_id not in connus:
        raise HTTPException(400, "Parcours inconnu : %s" % parcours_id)
    with closing(connexion()) as conn:
        curseur = conn.execute(
            "INSERT INTO sortie (parcours_id, jour, km, minutes, temps, chemins,"
            " ressenti, mot) VALUES (?,?,?,?,?,?,?,?)",
            (parcours_id, jour or date.today().isoformat(), km, minutes,
             temps, chemins, ressenti, mot))
        conn.commit()
        return JSONResponse({"id": curseur.lastrowid}, status_code=201)


@app.post("/api/sorties/{sortie_id}/trace")
async def depose_la_trace(sortie_id: int, fichier: UploadFile) -> JSONResponse:
    """Recoit le GPX reellement suivi, tel que l'application du telephone l'exporte."""
    if not (fichier.filename or "").lower().endswith(".gpx"):
        raise HTTPException(400, "On attend un fichier .gpx")
    contenu = await fichier.read()
    if len(contenu) > TAILLE_MAX:
        raise HTTPException(413, "Fichier trop gros (%d Mo au maximum)"
                            % (TAILLE_MAX // 1024 // 1024))
    with closing(connexion()) as conn:
        if conn.execute("SELECT 1 FROM sortie WHERE id = ?", (sortie_id,)).fetchone() is None:
            raise HTTPException(404, "Cette sortie n'existe pas")
        nom = "%d.gpx" % sortie_id
        (TRACES / nom).write_bytes(contenu)
        conn.execute("UPDATE sortie SET trace = ? WHERE id = ?", (nom, sortie_id))
        conn.commit()
    return JSONResponse({"trace": nom})


@app.get("/api/sorties/{sortie_id}/trace")
def relis_la_trace(sortie_id: int) -> FileResponse:
    with closing(connexion()) as conn:
        ligne = conn.execute("SELECT trace FROM sortie WHERE id = ?",
                             (sortie_id,)).fetchone()
    if ligne is None or not ligne["trace"]:
        raise HTTPException(404, "Aucune trace deposee pour cette sortie")
    return FileResponse(TRACES / ligne["trace"], media_type="application/gpx+xml")


@app.delete("/api/sorties/{sortie_id}")
def efface_une_sortie(sortie_id: int) -> JSONResponse:
    with closing(connexion()) as conn:
        ligne = conn.execute("SELECT trace FROM sortie WHERE id = ?",
                             (sortie_id,)).fetchone()
        if ligne is None:
            raise HTTPException(404, "Cette sortie n'existe pas")
        if ligne["trace"]:
            (TRACES / ligne["trace"]).unlink(missing_ok=True)
        conn.execute("DELETE FROM sortie WHERE id = ?", (sortie_id,))
        conn.commit()
    return JSONResponse({"efface": sortie_id})
