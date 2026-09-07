/* Ce qui fait qu'on peut marcher sans reseau.
 *
 * Emporter le fond de carte sur le NAS ne suffit pas : au fond d'un bois, le
 * telephone ne joint pas le NAS du tout. Ni la page, ni le catalogue, ni les
 * traces, ni les carreaux. Tout ce qui doit exister en foret doit donc etre
 * garde par le telephone lui-meme, et c'est le travail de ce fichier.
 *
 * Trois regimes, selon ce qu'on demande :
 *
 * - la coquille de l'application (la page, Leaflet, ses images) change
 *   rarement et doit s'ouvrir instantanement : le cache d'abord ;
 * - le catalogue et les traces changent quand on recalcule, et le nombre de
 *   sorties notees change souvent : le reseau d'abord, le cache en secours,
 *   et on rafraichit le cache a chaque reussite ;
 * - les carreaux de carte ne changent jamais : le cache d'abord, toujours.
 *
 * Rien n'est mis en cache par surprise. Les carreaux d'une boucle ne sont
 * emportes que lorsqu'on ouvre cette boucle -- geste qu'on fait de toute
 * facon avant de partir -- ou lorsqu'on demande explicitement les dix.
 */

/* Le serveur remplace ce jeton par la version de l'image. Les octets de ce
   fichier changent donc a chaque deploiement, ce qui declenche la
   reinstallation du service worker : sans cela une nouvelle version du site
   n'atteignait jamais le telephone, la page etant servie depuis le cache
   meme quand on demandait explicitement de le contourner. */
const VERSION = "__VERSION__";

/* La coquille et les donnees portent la version : un deploiement les remplace.
   Les carreaux, non -- ils ne dependent pas du code, et les jeter a chaque
   mise a jour ferait perdre un quart d'heure de telechargement pour rien. */
const COQUILLE = "olifant-coquille-" + VERSION;
const DONNEES = "olifant-donnees-" + VERSION;
const CARREAUX = "olifant-carreaux";

const A_EMPORTER = [
  "/",
  "/vendor/leaflet.js",
  "/vendor/leaflet.css",
];

self.addEventListener("install", evenement => {
  evenement.waitUntil((async () => {
    const cache = await caches.open(COQUILLE);
    // Une image de Leaflet absente ne doit pas faire echouer l'installation
    // entiere : on prend ce qui vient.
    // On force le contournement du cache HTTP : sans cela l'installation
    // remettrait en cache la page que le navigateur garde de son cote.
    await Promise.allSettled(A_EMPORTER.map(async url => {
      const reponse = await fetch(url, {cache: "reload"});
      if (reponse.ok) await cache.put(url, reponse);
    }));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", evenement => {
  evenement.waitUntil((async () => {
    const gardes = [COQUILLE, DONNEES, CARREAUX];
    const noms = await caches.keys();
    // On ne balaye que nos propres caches, et jamais celui des carreaux.
    await Promise.all(noms
      .filter(n => n.startsWith("olifant-") && !gardes.includes(n))
      .map(n => caches.delete(n)));
    await self.clients.claim();
    // Les pages ouvertes tournent encore sur l'ancienne coquille : on le leur
    // dit plutot que de recharger sous les pieds de quelqu'un qui marche.
    await annonce({type: "version", version: VERSION});
  })());
});

/* Tout compte rendu part vers toutes les pages ouvertes, et non vers
   l'expediteur d'un message. Au tout premier chargement, une page n'est pas
   encore controlee par le service worker : `evenement.source` valait alors
   null, le travail se faisait mais personne n'en etait informe -- le bouton
   restait a « Emporter » alors que les carreaux etaient deja pris. */
async function annonce(nouvelle){
  const pages = await self.clients.matchAll({includeUncontrolled: true,
                                             type: "window"});
  pages.forEach(page => page.postMessage(nouvelle));
}

/* ------------------------------------------------------------- strategies */

async function cacheDAbord(requete, nomDuCache){
  const cache = await caches.open(nomDuCache);
  const garde = await cache.match(requete);
  if (garde) return garde;
  const reponse = await fetch(requete);
  if (gardable(reponse)) cache.put(requete, reponse.clone());
  return reponse;
}

/* Une image demandee a un autre domaine revient « opaque » : on ne peut pas
   lire son statut, et `ok` vaut faux meme quand tout s'est bien passe. Une
   premiere version ne gardait donc jamais les carreaux d'OpenStreetMap -- ceux
   des zones hors des parcours ne survivaient pas a la perte du reseau, alors
   qu'on venait de les regarder. */
function gardable(reponse){
  return reponse.ok || (reponse.type === "opaque" && reponse.status === 0);
}

async function reseauDAbord(requete, nomDuCache){
  const cache = await caches.open(nomDuCache);
  try{
    const reponse = await fetch(requete);
    if (reponse.ok) cache.put(requete, reponse.clone());
    return reponse;
  }catch(e){
    const garde = await cache.match(requete);
    if (garde) return garde;
    throw e;
  }
}

self.addEventListener("fetch", evenement => {
  const requete = evenement.request;
  if (requete.method !== "GET") return;         // noter une sortie exige le reseau
  const url = new URL(requete.url);
  const local = url.origin === self.location.origin;

  // Les carreaux, d'ou qu'ils viennent : ils ne changent jamais.
  if ((local && url.pathname.startsWith("/tuiles/"))
      || url.hostname.endsWith("tile.openstreetmap.org")){
    // On laisse l'echec remonter tel quel plutot que de le remplacer par une
    // erreur fabriquee. La nuance compte : une reponse d'erreur forgee fait
    // marquer le carreau comme definitivement manquant, et le trou reste dans
    // la carte jusqu'au rechargement de la page, meme si le reseau revient
    // dans la seconde. Une erreur ordinaire, elle, laisse Leaflet redemander
    // le carreau au prochain deplacement.
    evenement.respondWith(cacheDAbord(requete, CARREAUX));
    return;
  }
  if (!local) return;

  // Un GPX ou un KML qu'on telecharge : c'est un fichier qu'on enregistre,
  // pas une ressource de la page. On le laisse passer.
  if (url.pathname.startsWith("/telecharge/")) return;

  if (url.pathname.startsWith("/api/")){
    evenement.respondWith(reseauDAbord(requete, DONNEES));
    return;
  }
  if (url.pathname === "/" || url.pathname.startsWith("/vendor/")){
    evenement.respondWith(cacheDAbord(requete, COQUILLE));
  }
});

/* ------------------------------------------- emporter une boucle a la main */

self.addEventListener("message", evenement => {
  const ordre = evenement.data || {};
  if (ordre.type !== "emporte") return;
  evenement.waitUntil(emporte(ordre.parcours, ordre.urls || []));
});



/* Le compte rendu nomme la boucle dont il parle. Sans cela la page devait se
   fier a une variable disant « celle qu'on emporte en ce moment », qui pouvait
   avoir change entre l'ordre et la reponse : on marquait alors la mauvaise
   boucle comme emportee, voire aucune. */
async function emporte(parcours, urls){
  const carreaux = await caches.open(CARREAUX);
  const donnees = await caches.open(DONNEES);

  // Le catalogue et les traces d'abord : sans eux, les carreaux ne servent a
  // rien -- on aurait un fond de carte et aucune trace a suivre dessus.
  await Promise.allSettled(["/api/parcours", "/api/traces.geojson", "/api/fond"]
    .map(async url => {
      const reponse = await fetch(url);
      if (reponse.ok) await donnees.put(url, reponse);
    }));

  let pris = 0, rates = 0;
  // Par petits paquets : lancer cent requetes d'un coup fait ramer le
  // telephone et n'accelere rien.
  for (let i = 0; i < urls.length; i += 6){
    const paquet = urls.slice(i, i + 6);
    const resultats = await Promise.allSettled(paquet.map(async url => {
      if (await carreaux.match(url)) return;    // deja emporte
      const reponse = await fetch(url);
      if (!reponse.ok) throw new Error(String(reponse.status));
      await carreaux.put(url, reponse);
    }));
    resultats.forEach(r => r.status === "fulfilled" ? pris++ : rates++);
    await annonce({type: "avancement", parcours, pris, rates,
                   total: urls.length});
  }
  await annonce({type: "emporte", parcours, pris, rates, total: urls.length});
}
