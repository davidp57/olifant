"""Le carnet vu par l'interface : lister ses sorties, revoir sa trace.

Rien de tout cela ne sort de la machine : la base et les fichiers vivent dans
un dossier temporaire propre a chaque test.
"""

import importlib

import pytest
from fastapi.testclient import TestClient

ENTETE = ('<?xml version="1.0" encoding="UTF-8"?>'
          '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">')


def gpx_de(points):
    lignes = "".join('<trkpt lat="%s" lon="%s"><ele>200</ele></trkpt>' % (lat, lon)
                     for lon, lat in points)
    return ENTETE + "<trk><trkseg>%s</trkseg></trk></gpx>" % lignes


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Une application neuve, dont les ecritures vont dans tmp_path."""
    sortie = tmp_path / "sortie"
    sortie.mkdir()
    # Le catalogue minimal que le serveur sert : il ne calcule rien lui-meme.
    (sortie / "parcours.json").write_text(
        '{"titre":"Olifant","accroche":"","parcours":[{"id":"boucle","nom":"La boucle",'
        '"resume":"","acces":"a pied","parking":"","themes":[],"couleur":"#1E3B34",'
        '"km":10.0,"montee":100,"chemin":50,"bitume":10,"route":40,"balise":0,'
        '"depart":"Gare","etapes":[]}]}', encoding="utf-8")
    monkeypatch.setenv("OLIFANT_SORTIE", str(sortie))
    monkeypatch.setenv("OLIFANT_DATA", str(tmp_path / "ecriture"))

    from olifant import api
    importlib.reload(api)
    with TestClient(api.app) as c:
        yield c


def note_une_sortie(client, jour="2026-09-07"):
    reponse = client.post("/api/sorties", data={"parcours_id": "boucle", "jour": jour})
    assert reponse.status_code == 201
    return reponse.json()["id"]


class TestListe:
    def test_liste_vide_au_depart(self, client):
        assert client.get("/api/sorties").json() == []

    def test_ne_rend_que_les_sorties_de_la_boucle_demandee(self, client):
        note_une_sortie(client)
        reponse = client.get("/api/sorties", params={"parcours_id": "boucle"})
        assert len(reponse.json()) == 1
        assert client.get("/api/sorties", params={"parcours_id": "autre"}).json() == []

    def test_la_plus_recente_d_abord(self, client):
        note_une_sortie(client, jour="2026-01-15")
        note_une_sortie(client, jour="2026-09-07")
        jours = [s["jour"] for s in client.get("/api/sorties").json()]
        assert jours == ["2026-09-07", "2026-01-15"]


class TestTraceDessinable:
    def test_rend_la_trace_en_geojson(self, client):
        sortie_id = note_une_sortie(client)
        client.post("/api/sorties/%d/trace" % sortie_id,
                    files={"fichier": ("marche.gpx",
                                       gpx_de([(6.0, 49.0), (6.0, 49.01), (6.0, 49.02)]),
                                       "application/gpx+xml")})

        forme = client.get("/api/sorties/%d/trace.geojson" % sortie_id).json()
        assert forme["geometry"]["type"] == "MultiLineString"
        assert forme["properties"]["km"] == pytest.approx(2.22, abs=0.05)
        assert "2026-09-07" in forme["properties"]["nom"]

    def test_dit_qu_il_n_y_a_rien_plutot_que_de_servir_du_vide(self, client):
        sortie_id = note_une_sortie(client)
        reponse = client.get("/api/sorties/%d/trace.geojson" % sortie_id)
        assert reponse.status_code == 404

    def test_sortie_inconnue(self, client):
        assert client.get("/api/sorties/999/trace.geojson").status_code == 404

    def test_un_gpx_sans_trace_est_signale_clairement(self, client):
        """Le fichier a ete accepte au depot -- on ne le lisait pas. C'est a
        l'affichage qu'on decouvre qu'il ne contient aucun segment."""
        sortie_id = note_une_sortie(client)
        sans_trace = ENTETE + '<wpt lat="49.0" lon="6.0"><name>Depart</name></wpt></gpx>'
        client.post("/api/sorties/%d/trace" % sortie_id,
                    files={"fichier": ("points.gpx", sans_trace, "application/gpx+xml")})

        reponse = client.get("/api/sorties/%d/trace.geojson" % sortie_id)
        assert reponse.status_code == 422
        assert "aucun segment" in reponse.json()["detail"]

    def test_le_gpx_brut_reste_telechargeable(self, client):
        """L'affichage ne remplace pas le fichier d'origine : on doit pouvoir
        le recuperer tel qu'il a ete rapporte."""
        sortie_id = note_une_sortie(client)
        contenu = gpx_de([(6.0, 49.0), (6.0, 49.01)])
        client.post("/api/sorties/%d/trace" % sortie_id,
                    files={"fichier": ("marche.gpx", contenu, "application/gpx+xml")})

        brut = client.get("/api/sorties/%d/trace" % sortie_id)
        assert brut.status_code == 200
        assert b"trkpt" in brut.content

    def test_effacer_la_sortie_efface_sa_trace(self, client):
        sortie_id = note_une_sortie(client)
        client.post("/api/sorties/%d/trace" % sortie_id,
                    files={"fichier": ("m.gpx", gpx_de([(6.0, 49.0), (6.0, 49.01)]),
                                       "application/gpx+xml")})
        assert client.delete("/api/sorties/%d" % sortie_id).status_code == 200
        assert client.get("/api/sorties/%d/trace.geojson" % sortie_id).status_code == 404
