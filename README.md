# Olifant

Préparer, consulter et emporter des randonnées à pied autour de Metz.

On décrit des lieux et l'ordre dans lequel on les enchaîne ; une commande
calcule le tracé réel sur les chemins, **mesure ce qu'il vaut** et fabrique les
GPX et les KML. Un petit serveur les présente sur une carte et recueille ce
qu'on rapporte de la balade.

---

## Ce qui compte : le tracé suit vraiment les chemins

C'était le point faible de la version précédente, et c'est la raison d'être de
celle-ci. Le calcul se fait avec **BRouter, profil `hiking-beta`**, qui
privilégie les sentiers et sait lire les itinéraires de randonnée balisés
d'OpenStreetMap. Le choix n'est pas une préférence, il est mesuré :

| profil | Mont Saint-Quentin | plateau de Lorry |
|---|---|---|
| `trekking` (le réflexe) | 15,1 km — 29 % chemin, **53 % bitume** | 14,7 km — 28 % chemin, **64 % bitume** |
| **`hiking-beta`** | 15,3 km — **48 % chemin**, 21 % bitume | **13,6 km** — **51 % chemin**, 39 % bitume |

L'ancien `build.py` utilisait `valhalla / pedestrian`, un profil piéton *urbain*
conçu pour les trottoirs : il colle aux routes et coupe droit là où il ne trouve
rien.

### Le contrôle qualité

Le routeur peut se tromper sans le dire. Quatre contrôles tournent à chaque
calcul et signalent, avant qu'on parte marcher :

- **l'étape rattachée ailleurs** — un point posé au milieu d'un bois sur une vue
  satellite se retrouve accroché à 300 m de là, sur la route qui longe le bois,
  et le parcours ne passe pas où on croyait ;
- **la boucle qui ne boucle pas** — départ et arrivée ne coïncident pas ;
- **l'aller-retour déguisé** — la moitié du parcours refait le même chemin, ce
  qui se voit mal sur une carte et très bien en marchant ;
- **le bitume** — au-delà de 45 %, le parcours est signalé.

## Les parcours

Cinq boucles, toutes au départ du parvis de la gare de Metz : abrité, un café
ouvert tôt, et tout le monde sait où c'est.

| parcours | distance | D+ | chemins | balisé |
|---|---|---|---|---|
| La Seille et le fort de Queuleu | 10,3 km | 61 m | 47 % | — |
| Les bois de l'est | 12,3 km | 71 m | 38 % | 17 % |
| Les deux rives | 13,1 km | 20 m | 32 % | 18 % |
| La Seille en amont | 15,2 km | 31 m | 54 % | — |
| Le versant de Plappeville | 15,8 km | 160 m | 33 % | 21 % |

Des boucles au départ en voiture (Mont Saint-Quentin, côtes de Jussy, vallée de
Gorze, vallée de la Canner, pelouses de Montenach) attendent dans
`data/parcours-voiture-en-attente.yaml` — elles mesurent jusqu'à **87 % de
chemin et 0 % de bitume**, mais demandaient encore du calage.

## Utiliser

### Calculer

```bash
python -m olifant calcule
```

Un seul appel réseau par parcours, en cache sur disque : un deuxième calcul ne
rappelle rien. `--hors-ligne` se contente du cache, `--profil` change de moteur.

Deux commandes servent à composer un nouveau parcours sans salir le fichier :

```bash
python -m olifant essaie gare parc-seille queuleu montigny gare
python -m olifant accroche bois-macabee
```

`essaie` mesure une suite d'étapes et ne l'enregistre pas ; `accroche` dit à
quelle distance le routeur rattache un point, et donne les coordonnées corrigées.

### Consulter

```bash
python -m uvicorn olifant.api:app --port 8137
```

Puis <http://localhost:8137> : la carte, la liste, le détail des étapes avec
leurs notes, et le téléchargement GPX ou KML.

### Sur le NAS

```bash
docker compose up -d --build
```

Le service ne calcule rien et n'appelle aucun routeur : il sert ce que
`calcule` a produit. Le NAS peut donc être éteint sans que les traces déjà
emportées cessent d'exister, et le remettre debout ne dépend d'aucun service
extérieur. Leaflet est servi par le conteneur, pas par un CDN.

Le volume `./carnet` contient ce qui naît de l'usage — les sorties notées et les
traces réellement suivies. Une mise à jour de l'image n'y touche pas.

### Sur le terrain

Le GPX est du **GPX 1.1 standard avec altitude**, avec la trace et les étapes en
points de passage nommés : c'est ce qu'attend Iphigénie pour afficher une trace
à suivre. Le KML va dans Google My Maps ou Google Earth.

## Ajouter un parcours

Tout tient dans `data/parcours.yaml`. On n'y écrit que ce qu'un humain sait :

```yaml
points:
  bois-macabee:
    nom: Bois de la Macabee
    lon: 6.232106
    lat: 49.101397
    note: Le plus grand massif accessible a pied depuis Metz.

parcours:
  - id: bois-de-lest
    nom: Les bois de l'est
    etapes: [gare, parc-seille, queuleu, bois-macabee, gloucester, cheneau, gare]
```

La distance, le dénivelé et la part de chemin **ne se saisissent pas** : ils sont
mesurés. Composer avec `essaie` jusqu'à ce que la distance et le pourcentage de
chemin conviennent, puis inscrire les étapes retenues et relancer `calcule`.

## Structure

| | |
|---|---|
| `data/parcours.yaml` | le seul fichier écrit à la main |
| `olifant/routage.py` | BRouter, cache disque, réessais patients |
| `olifant/qualite.py` | les quatre contrôles, et leurs seuils |
| `olifant/export.py` | GPX, KML, GeoJSON |
| `olifant/api.py` | le serveur et le carnet |
| `olifant/web/` | la page, Leaflet compris |
| `data/cache/` | les réponses du routeur, versionnées : tout se rejoue hors ligne |

## Tests

```bash
python -m pytest
```

44 tests, sans réseau.

## Un mot sur les services publics

BRouter, Nominatim et Overpass sont gratuits et tenus par des bénévoles. Le
routeur attend deux secondes entre deux appels et patiente quand on lui demande
de ralentir. Gardez le cache, évitez les recalculs inutiles.
