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

Treize parcours. Les cinq premiers partent du parvis de la gare de Metz :
abrité, un café ouvert tôt, et tout le monde sait où c'est.

| parcours | distance | D+ | chemins | balisé |
|---|---|---|---|---|
| La Seille et le fort de Queuleu | 10,3 km | 61 m | 47 % | — |
| Les bois de l'est | 12,3 km | 71 m | 38 % | 17 % |
| Les deux rives | 13,1 km | 20 m | 32 % | 18 % |
| La Seille en amont | 15,2 km | 31 m | 54 % | — |
| Le versant de Plappeville | 15,8 km | 160 m | 33 % | 21 % |

Les six suivants demandent un quart d'heure à trois quarts d'heure de voiture
pour rejoindre le départ. Elles quittent la ville, et ça se voit : presque pas
de bitume, beaucoup plus de dénivelé, et des tronçons déjà balisés.

| parcours | départ | distance | D+ | chemins | balisé |
|---|---|---|---|---|---|
| Le tour du Mont Saint-Quentin | Scy-Chazelles | 10,8 km | 284 m | 42 % | 38 % |
| La vallée de la Canner | Kédange-sur-Canner | 15,0 km | 249 m | 87 % | 8 % |
| Les côtes de Jussy | Sainte-Ruffine | 15,2 km | 341 m | 50 % | 29 % |
| Les pelouses de Montenach | Sierck-les-Bains | 15,5 km | 330 m | 54 % | 57 % |
| L'aqueduc et la corniche de la Fraze | Ars-sur-Moselle | 15,7 km | 208 m | 68 % | 51 % |
| Le tour du vallon de Gorze | Gorze | 14,8 km | 222 m | 68 % | — |

### Aller au centre commercial à pied

Les deux derniers ne cherchent pas la campagne : ils relient la rue des
Parmentiers au centre commercial de Borny — l'ancien Cora, passé sous
l'enseigne Carrefour — et en reviennent. Le but fixe les deux extrémités, et
la marge de manœuvre est mince : cinq corridors de retour ont été mesurés
(parc de la Seille, parc de la Chêneau, parc de Gloucester, Technopôle,
Queuleu) et **tous donnent 10,3 km**. Descendre sous 10 km oblige à refaire le
chemin à l'envers. Les deux options sont là, au choix.

| parcours | distance | D+ | chemins | balisé | forme |
|---|---|---|---|---|---|
| La Seille et les commerces de Borny | 10,3 km | 55 m | 36 % | 20 % | boucle, 8 % de recouvrement |
| Borny par le plus court | 9,6 km | 38 m | 39 % | 40 % | aller-retour assumé, moitié du tracé refait |

Le second sort exprès du cadre : il déclenche l'alerte « aller-retour déguisé »
du contrôle qualité, et c'est voulu. Quand le but est le but, la boucle n'est
pas toujours ce qu'on cherche.

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

Sur grand écran, la liste et la carte tiennent côte à côte. Sur téléphone,
elles ne le peuvent pas — la place manque — et l'interface montre **une chose
à la fois** : la liste des boucles, la carte, ou une boucle. La barre du bas
passe de l'une à l'autre, le bouton retour du téléphone referme une boucle.

Choisir une boucle fait entrer en **consultation**, aux deux tailles d'écran :
la liste et les filtres s'effacent, la boucle prend toute la place, et un lien
ramène en arrière. Tant qu'on regarde celle-ci, le reste n'a rien à dire.

Les filtres « à pied / en voiture » et le tri sont retenus d'une visite à
l'autre. Dans la liste, une boucle se résume à sa distance, son dénivelé et sa
jauge de revêtement : de quoi choisir sans lire. Le reste — résumé, étapes,
téléchargements — apparaît quand on l'ouvre, et les boutons restent collés en
bas de l'écran plutôt qu'au bout du défilement.

Chaque étape porte **le kilomètre auquel on y arrive** et se déplie sur ce
qu'il y a autour : de l'eau, un point de vue, un abri, un café, du patrimoine.
Ces repères sont relevés dans OpenStreetMap, jamais saisis à la main.

Un interrupteur les affiche **tous d'un coup sur la carte**, avec une icône par
genre — goutte, montagne, tasse, tour, arbre. C'est ainsi qu'on répond à « où
est l'eau sur ce trajet ? » sans déplier les sept étapes une par une. L'état
est retenu d'une visite à l'autre.

### Marcher avec

Le bouton **Me situer** affiche la position sur la trace et répond aux trois
questions qu'on se pose à un embranchement sans panneau : à quel kilomètre on
en est, ce qu'il reste, et quelle est la prochaine étape. Il prévient aussi
quand on s'est écarté de plus de soixante mètres. L'écran est maintenu allumé
pendant le suivi.

Il donne surtout **la direction à suivre**, sur la carte comme en toutes
lettres : une flèche tourne autour du point de position vers l'étape à
rejoindre — utile surtout quand cette étape est hors de l'écran, ce qui est le
cas le plus fréquent — et la ligne de texte donne la distance.

Reste à savoir de quel côté tourner. Le GPS ne connaît la direction que par
le déplacement, donc en mouvement : « 27° à droite », ou « tout droit ».
Immobile à un carrefour — exactement là où l'on hésite — il n'a rien à en
dire, et c'est **la boussole** qui prend le relais quand l'appareil en a une.
Sur iPhone elle demande une autorisation, réclamée au moment où l'on touche
« Me situer ». Faute des deux, le cap absolu et son aire restent affichés :
« cap 117° (sud-est) ».

Deux limites à connaître. La position exige **HTTPS** : en HTTP, même sur le
réseau local, le navigateur la refuse sans rien demander. Et un navigateur ne
suit pas la position en arrière-plan : téléphone rangé ou verrouillé, le suivi
s'interrompt. Se situer quand on sort le téléphone marche très bien ;
enregistrer une trace de quatre heures, non — c'est le travail d'une
application installée comme Iphigénie.

### Revoir une sortie

Sous chaque boucle, les fois où on l'a marchée. Quand une sortie a un GPX,
**Voir la trace** le dessine en pointillé par-dessus le tracé prévu : on voit
où on a coupé, où on s'est perdu, où on a fait un détour.

Le fichier est relu avec un parseur XML durci, et **débruité avant d'être
mesuré**. Sans cela, le tremblement du GPS s'ajoute au chemin : sur un essai,
10,3 km de marche donnaient 13,5 km et 660 m de dénivelé au lieu de 61.

### Emporter le fond de carte

En forêt, il n'y a pas de réseau. **Et un point qu'il faut avoir en tête :
sans réseau, le téléphone ne joint pas non plus le NAS** — ni la page, ni le
catalogue, ni les traces, ni les carreaux. Emporter le fond de carte sur le
serveur ne suffit donc pas à marcher hors réseau ; ça évite seulement de
dépendre d'OpenStreetMap. Ce qui permet de marcher, c'est que **le téléphone**
garde tout.

D'où deux dispositifs, l'un sur le serveur, l'autre dans le navigateur.

**Le fond voyage dans l'image**, récupéré au moment de la construction : 997
carreaux pour les dix boucles, du zoom 13 au zoom 16, une quinzaine de
mégaoctets. Un cache d'Actions évite de les reprendre à chaque push — seul un
changement de traces en redemande.

C'est une correction, et elle vaut d'être expliquée. Le service les
téléchargeait lui-même au premier démarrage, un carreau par seconde pendant un
quart d'heure. Or **les serveurs de tuiles comptent par adresse IP**, et celle
du NAS est celle de la maison : pendant qu'il préparait le hors-ligne, il
faisait refuser les tuiles du navigateur de la personne assise à côté — carte
en damier, sans explication. Le NAS n'appelle donc plus OpenStreetMap du tout.

En développement, la commande reste là :

```bash
python -m olifant tuiles --compte-seulement   # dit combien, sans rien prendre
python -m olifant tuiles                      # les prend, un par seconde
```

**Dans le navigateur**, un service worker garde la page, Leaflet, le catalogue
et les traces dès la première visite. Puis, quand on ouvre une boucle, le
bouton **Emporter pour hors réseau** prend ses carreaux — une centaine, un ou
deux mégaoctets, quelques secondes en Wi-Fi. On regarde la boucle chez soi
avant de partir, et elle est prête. Rien n'est téléchargé sans être demandé.

Le serveur ne dit pas seulement *s'il* a un fond, mais *lequel* : la page ne
réclame ainsi aucun carreau absent. Un couloir de traces n'est pas un
rectangle — cinquante kilomètres séparent Metz de Sierck — et une simple
emprise aurait fait demander des milliers de carreaux inexistants.

La carte empile deux fonds : les carreaux locaux **au-dessus** de ceux
d'OpenStreetMap. Là où le carreau local manque, on voit celui d'OSM à
travers ; là où le réseau manque, c'est l'inverse ; et quand les deux
manquent, restent la trace et la position.

### Savoir ce qui tourne

Le pied de la liste affiche la version de l'image et sa date de construction —
le commit court, inscrit par la construction. Sur un poste de développement,
il dit « dev ».

Ce n'est pas de la coquetterie. La page est servie par un service worker, donc
depuis un cache : sans ce numéro, on n'a aucun moyen de savoir si le NAS fait
tourner la dernière image, **ni de s'apercevoir qu'une mise à jour n'est jamais
arrivée jusqu'au téléphone**. Un service worker n'est réinstallé que si ses
octets changent ; le sien porte donc la version, ce qui suffit à le faire
changer à chaque déploiement. La page, elle, porte la version avec laquelle
elle a été servie : si le serveur en annonce une autre, elle propose de
recharger — sans le faire d'autorité, parce que quelqu'un peut être en train de
marcher en suivant la carte.

Les carreaux, eux, survivent aux mises à jour : leur cache n'est pas versionné.
Les jeter à chaque déploiement ferait reperdre le téléchargement pour rien.

### Relever ce qu'il y a autour des étapes

```bash
python -m olifant reperes                     # les dix boucles
python -m olifant reperes canner --hors-ligne # une seule, depuis le cache
```

Une requête Overpass par boucle, gardée sur disque. C'est lent (une minute et
demie par boucle) et volontairement séparé de `calcule` : un parcours doit
pouvoir se calculer sans dépendre d'Overpass, et `calcule` se passe du relevé
s'il n'existe pas.

### Sur le NAS

Depuis Portainer : **Stacks → Add stack → Web editor**, coller
`docker-compose.yml`, déployer. Puis <http://votre-nas:8137>. L'image est
construite par GitHub à chaque push et publiée sur `ghcr.io`, pour amd64 et
arm64.

En ligne de commande :

```bash
docker compose up -d
```

**Pour mettre à jour**, après un push sur `main` : dans Portainer, ouvrir la
stack et **Pull and redeploy**. En ligne de commande :

```bash
docker compose pull && docker compose up -d
```

Le service ne calcule aucune trace et n'interroge aucun routeur : il sert ce
que `calcule` a produit. Aucune visite ne déclenche d'appel vers l'extérieur.
La seule exception est une préparation unique au premier démarrage — le fond
de carte, décrit plus haut — qui se fait en tâche de fond et ne se reproduit
pas. Le NAS peut donc être éteint sans que les traces déjà emportées cessent
d'exister, et le remettre debout ne dépend d'aucun service extérieur. Leaflet
est servi par le conteneur, pas par un CDN.

Le volume nommé `carnet` contient ce qui naît de l'usage — les sorties notées et les
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
| `olifant/jalons.py` | à quel kilomètre tombe chaque étape |
| `olifant/reperes.py` | ce qu'OSM sait autour des étapes |
| `olifant/tuiles.py` | le fond de carte à emporter |
| `olifant/suivi.py` | relire un GPX rapporté d'une sortie |
| `olifant/export.py` | GPX, KML, GeoJSON |
| `olifant/api.py` | le serveur et le carnet |
| `olifant/web/` | la page, Leaflet compris |
| `olifant/web/sw.js` | ce qui fait que le téléphone marche sans réseau |
| `data/cache/` | les réponses du routeur, versionnées : tout se rejoue hors ligne |
| `data/tuiles/` | le fond de carte emporté, hors dépôt (19 Mo de PNG) |

## Tests

```bash
python -m pytest
```

149 tests, sans réseau.

## Un mot sur les services publics

BRouter, Overpass et les serveurs de tuiles d'OpenStreetMap sont gratuits et
tenus par des bénévoles. Chaque commande qui les sollicite attend entre deux
appels, patiente quand on lui demande de ralentir, et **garde tout sur disque
pour ne jamais redemander deux fois la même chose**.

Deux décisions viennent de là. Le relevé des repères ne demande plus les arbres
ni les bancs : à eux seuls, ils représentaient jusqu'à 589 et 401 réponses pour
un seul parcours, l'essentiel du volume, sans rien apprendre à qui marche. Et le
fond de carte emporté se limite au couloir des traces et s'arrête au zoom 16 —
997 carreaux pour les dix boucles, une quinzaine de mégaoctets, pris une seule
fois à raison d'un par seconde. C'est un usage personnel et borné, pas une
aspiration ; si vous élargissez les zooms ou la marge, le compte grimpe vite
(`--compte-seulement` le dit avant de rien télécharger).

Gardez le cache, évitez les recalculs inutiles.
