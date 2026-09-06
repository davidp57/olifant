"""Le serveur, teste de bout en bout sur une base jetable.

Chaque test part d'une base vide dans un dossier temporaire : on ne touche
jamais au carnet reel, et l'ordre des tests n'a pas d'importance.
"""

import pytest
from fastapi.testclient import TestClient

from olifant import api


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "BASE", tmp_path / "carnet.db")
    monkeypatch.setattr(api, "TRACES", tmp_path / "traces")
    (tmp_path / "traces").mkdir()
    with TestClient(api.app) as c:
        yield c


def premier_parcours(client):
    return client.get("/api/parcours").json()["parcours"][0]["id"]


class TestLecture:
    def test_la_page_se_sert(self, client):
        reponse = client.get("/")
        assert reponse.status_code == 200
        assert "Olifant" in reponse.text

    def test_le_catalogue_porte_les_mesures(self, client):
        parcours = client.get("/api/parcours").json()["parcours"]
        assert parcours
        for p in parcours:
            assert p["km"] > 0
            assert 0 <= p["chemin"] <= 100
            assert p["etapes"] and p["etapes"][0]["depart"] is True

    def test_le_gpx_se_telecharge(self, client):
        reponse = client.get("/telecharge/%s.gpx" % premier_parcours(client))
        assert reponse.status_code == 200
        assert reponse.text.lstrip().startswith("<?xml")

    def test_on_ne_sert_que_du_gpx_et_du_kml(self, client):
        assert client.get("/telecharge/x.db").status_code == 404

    def test_on_ne_peut_pas_remonter_hors_du_dossier(self, client):
        # Une URL bricolee ne doit pas donner acces au reste du disque.
        for tordu in ("..%2f..%2fcarnet.db", "....//....//data/carnet.db"):
            reponse = client.get("/telecharge/%s.gpx" % tordu)
            assert reponse.status_code == 404, tordu


class TestCarnet:
    def test_on_note_une_sortie_et_on_la_relit(self, client):
        pid = premier_parcours(client)
        reponse = client.post("/api/sorties", data={
            "parcours_id": pid, "jour": "2026-09-01", "km": 12.4, "minutes": 175,
            "temps": "Couvert", "chemins": "Humide", "ressenti": "Bien",
            "mot": "Chevreuils avant le bois."})
        assert reponse.status_code == 201
        sorties = client.get("/api/sorties").json()
        assert len(sorties) == 1
        assert sorties[0]["mot"] == "Chevreuils avant le bois."
        assert sorties[0]["km"] == 12.4

    def test_le_compteur_de_sorties_remonte_dans_le_catalogue(self, client):
        pid = premier_parcours(client)
        assert client.get("/api/parcours").json()["parcours"][0]["fois"] == 0
        client.post("/api/sorties", data={"parcours_id": pid})
        assert client.get("/api/parcours").json()["parcours"][0]["fois"] == 1

    def test_un_parcours_inconnu_est_refuse(self, client):
        reponse = client.post("/api/sorties", data={"parcours_id": "fantome"})
        assert reponse.status_code == 400

    def test_la_date_du_jour_sert_de_defaut(self, client):
        client.post("/api/sorties", data={"parcours_id": premier_parcours(client)})
        assert client.get("/api/sorties").json()[0]["jour"]


class TestTraceReelle:
    def depose(self, client, sortie_id, nom="reel.gpx", contenu=b"<gpx/>"):
        return client.post("/api/sorties/%d/trace" % sortie_id,
                           files={"fichier": (nom, contenu, "application/gpx+xml")})

    def note(self, client):
        return client.post("/api/sorties",
                           data={"parcours_id": premier_parcours(client)}).json()["id"]

    def test_on_depose_la_trace_suivie_et_on_la_recupere(self, client):
        sortie = self.note(client)
        assert self.depose(client, sortie).status_code == 200
        relu = client.get("/api/sorties/%d/trace" % sortie)
        assert relu.status_code == 200 and relu.content == b"<gpx/>"

    def test_seul_le_gpx_est_accepte(self, client):
        assert self.depose(client, self.note(client), nom="photo.jpg").status_code == 400

    def test_une_sortie_qui_n_existe_pas_refuse_la_trace(self, client):
        assert self.depose(client, 999).status_code == 404

    def test_un_fichier_demesure_est_refuse(self, client, monkeypatch):
        monkeypatch.setattr(api, "TAILLE_MAX", 10)
        assert self.depose(client, self.note(client),
                           contenu=b"x" * 100).status_code == 413

    def test_effacer_une_sortie_emporte_sa_trace(self, client):
        sortie = self.note(client)
        self.depose(client, sortie)
        assert (api.TRACES / ("%d.gpx" % sortie)).exists()
        assert client.delete("/api/sorties/%d" % sortie).status_code == 200
        assert not (api.TRACES / ("%d.gpx" % sortie)).exists()
        assert client.get("/api/sorties").json() == []
