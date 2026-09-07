"""Le fond de carte emporte, vu par le serveur.

Ce qui doit tenir : l'inventaire dit la verite meme quand des carreaux
arrivent apres coup, on ne sort pas du dossier servi, et le service worker
est distribue depuis la racine sans quoi sa portee ne couvre rien.
"""

import importlib

import pytest
from fastapi.testclient import TestClient

CATALOGUE = ('{"titre":"Olifant","accroche":"","parcours":[{"id":"boucle",'
             '"nom":"La boucle","resume":"","acces":"a pied","parking":"",'
             '"themes":[],"couleur":"#1E3B34","km":10.0,"montee":100,'
             '"chemin":50,"bitume":10,"route":40,"balise":0,"depart":"Gare",'
             '"etapes":[]}]}')
# Une trace de quelques centaines de metres : de quoi couvrir peu de carreaux.
TRACES = ('{"type":"FeatureCollection","features":[{"type":"Feature",'
          '"properties":{"id":"boucle","couleur":"#1E3B34"},'
          '"geometry":{"type":"LineString","coordinates":'
          '[[6.177,49.109],[6.178,49.110],[6.179,49.111]]}}]}')

PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 24)


@pytest.fixture
def client(tmp_path, monkeypatch):
    sortie = tmp_path / "sortie"
    sortie.mkdir()
    (sortie / "parcours.json").write_text(CATALOGUE, encoding="utf-8")
    (sortie / "traces.geojson").write_text(TRACES, encoding="utf-8")
    monkeypatch.setenv("OLIFANT_SORTIE", str(sortie))
    monkeypatch.setenv("OLIFANT_DATA", str(tmp_path / "ecriture"))
    monkeypatch.setenv("OLIFANT_TUILES", str(tmp_path / "tuiles"))
    # Le remplissage automatique n'a rien a faire dans un test : il irait
    # chercher un millier de carreaux sur les serveurs d'OpenStreetMap.
    monkeypatch.delenv("OLIFANT_TUILES_AUTO", raising=False)

    from olifant import api
    importlib.reload(api)
    with TestClient(api.app) as c:
        c.dossier_tuiles = tmp_path / "tuiles"
        yield c


def pose_un_carreau(client, z, x, y):
    chemin = client.dossier_tuiles / str(z) / str(x) / ("%d.png" % y)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(PNG)
    return chemin


class TestInventaire:
    def test_dit_qu_il_n_y_a_rien_quand_rien_n_a_ete_emporte(self, client):
        fond = client.get("/api/fond").json()
        assert fond == {"emporte": False, "zooms": [], "carreaux": 0,
                        "carreaux_par_zoom": {}}

    def test_liste_les_carreaux_par_zoom_et_colonne(self, client):
        pose_un_carreau(client, 15, 16960, 11209)
        pose_un_carreau(client, 15, 16960, 11210)
        pose_un_carreau(client, 14, 8480, 5604)

        fond = client.get("/api/fond").json()
        assert fond["emporte"] is True
        assert fond["zooms"] == [14, 15]
        assert fond["carreaux"] == 3
        assert fond["carreaux_par_zoom"]["15"]["16960"] == [11209, 11210]

    def test_voit_les_carreaux_arrives_apres_le_premier_appel(self, client):
        """Le bug que ce test existe pour empecher : une premiere version
        gardait l'inventaire en memoire, indexe sur la date du dossier racine
        -- qui ne change pas quand on ecrit dans 13/4240/2802.png. La page ne
        reclamait alors qu'une fraction des carreaux disponibles."""
        pose_un_carreau(client, 15, 16960, 11209)
        assert client.get("/api/fond").json()["carreaux"] == 1

        pose_un_carreau(client, 15, 16960, 11210)
        pose_un_carreau(client, 16, 33920, 22418)
        assert client.get("/api/fond").json()["carreaux"] == 3

    def test_ignore_un_fichier_mal_range(self, client):
        (client.dossier_tuiles / "15" / "abc").mkdir(parents=True)
        (client.dossier_tuiles / "15" / "abc" / "pas-un-nombre.png").write_bytes(PNG)
        pose_un_carreau(client, 15, 16960, 11209)
        assert client.get("/api/fond").json()["carreaux"] == 1


class TestUnCarreau:
    def test_sert_un_carreau_present(self, client):
        pose_un_carreau(client, 15, 16960, 11209)
        reponse = client.get("/tuiles/15/16960/11209.png")
        assert reponse.status_code == 200
        assert reponse.headers["content-type"] == "image/png"
        assert reponse.content.startswith(b"\x89PNG")

    @pytest.mark.parametrize("chemin", [
        "/tuiles/15/16960/99999.png",     # absent
        "/tuiles/25/1/1.png",             # zoom impossible
        "/tuiles/2/99/1.png",             # colonne hors du monde a ce zoom
    ])
    def test_repond_404_plutot_que_de_deviner(self, client, chemin):
        """Un 404 n'est pas une anomalie : la page empile cette couche par
        dessus celle d'OpenStreetMap et laisse voir a travers ce qui manque."""
        assert client.get(chemin).status_code == 404


class TestFondDUnParcours:
    def test_ne_donne_que_les_carreaux_reellement_presents(self, client):
        """On n'envoie pas le telephone chercher des carreaux introuvables."""
        vide = client.get("/api/fond/boucle").json()
        assert vide["carreaux"] == []
        assert vide["attendus"] > 0        # le couloir en demande, lui

        # On en pose un qui appartient au couloir de la trace.
        from olifant import tuiles
        besoin = sorted(tuiles.couloir([(6.177, 49.109), (6.179, 49.111)]),
                        key=lambda c: (c.z, c.x, c.y))
        pose_un_carreau(client, besoin[0].z, besoin[0].x, besoin[0].y)

        fond = client.get("/api/fond/boucle").json()
        assert fond["carreaux"] == ["/tuiles/" + besoin[0].chemin()]
        assert fond["octets"] == len(PNG)

    def test_parcours_inconnu(self, client):
        assert client.get("/api/fond/nulle-part").status_code == 404


class TestServiceWorker:
    def test_servi_depuis_la_racine(self, client):
        """Un service worker ne peut intercepter que ce qui est sous son
        chemin : place ailleurs qu'a la racine, il ne verrait ni la page ni
        les carreaux."""
        reponse = client.get("/sw.js")
        assert reponse.status_code == 200
        assert "javascript" in reponse.headers["content-type"]
        assert reponse.headers["service-worker-allowed"] == "/"
        assert "olifant" in reponse.text

    def test_n_est_pas_garde_en_cache_par_le_navigateur(self, client):
        """Sinon une correction du service worker n'atteindrait jamais le
        telephone qui tourne avec l'ancien."""
        assert "no-cache" in client.get("/sw.js").headers["cache-control"]
