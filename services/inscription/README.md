# Inscription des membres — MVP (la fiche part par e-mail)

En ligne sur <https://members.syntonie.be>, en mode test.

- `www/index.html` : la fiche, FR / NL / EN, en trois écrans : la fiche, la
  cotisation (25 €, par Citizen Pay ou par virement), la confirmation.
- `app.py` : sert la page, valide la fiche et l'envoie à `contact@syntonie.be`
  via Resend. Python seul, aucune dépendance.

## La cotisation

**Avec Citizen Pay** (`CITIZENPAY_PLACE` rempli), l'écran de cotisation montre
le QR d'une commande Citizen Pay de 25 €, comme l'écran du terminal. La
personne le scanne avec son téléphone, ou clique « Payer sur cet ordinateur »
(la page de paiement s'ouvre dans un nouvel onglet). Sous le QR, l'état suit
la commande : en attente du scan, scanné, confirmation en cours, payé. Une fois
payé, la fiche part toute seule et la confirmation dit « paiement confirmé »,
avec le numéro de commande.

- Le service crée la commande et relaie son état : la page ne parle qu'à lui
  (`connect-src 'self'`). Citizen Pay n'envoie ni retour ni notification ; la
  page redemande l'état toutes les 2 s.
- **Le serveur vérifie lui-même le paiement avant d'envoyer la fiche** : la
  commande doit être payée, de 25 € (`FEE_CENTS`), au lieu de l'association.
  Sinon rien ne part. L'e-mail dit « payée via Citizen Pay, commande n° …,
  vérifiée par le serveur ». Une commande payée ne vaut que pour une fiche.
- La commande est lisible par qui connaît son numéro. Sa description est
  `Cotisation <année> OpenFab`, **sans nom**.
- Un code non payé expire après 14 minutes (Citizen Pay annule la commande
  vers 15 minutes) : le QR se grise, « Nouveau code » en crée une autre.
- Rien n'est stocké. Le lien entre la page et sa commande est un jeton signé
  avec un secret tiré au démarrage : un redémarrage du service pendant un
  paiement renvoie la personne au virement.

**Autre possibilité**, plus discrète sous le QR : virement (IBAN,
communication `Cotisation <année> <Nom> <Prénom>`) ou carte au terminal de
l'accueil, puis le bouton « J'ai fait le virement » ou « J'ai payé à
l'accueil ».

**Sans Citizen Pay** (variable vide), ou si Citizen Pay ne répond pas, l'écran
est celui d'avant : QR de virement SEPA et les deux boutons.

Deux garde-fous, nés de l'expérience (des inscriptions en ligne jamais payées
s'ajoutaient à la liste des membres) :

- **Un code d'accueil** (`ACCESS_CODE`) est demandé en tête de fiche. Un·e
  bénévole le donne sur place : on ne s'inscrit pas sans venir à l'atelier.
- **Rien n'est envoyé avant le paiement.** La fiche part quand Citizen Pay
  confirme le paiement, ou quand la personne clique « J'ai fait le virement »
  ou « J'ai payé à l'accueil ». L'e-mail dit lequel. Qui s'arrête au QR ne
  laisse aucune trace.
- `www/qrcode.js` : qrcode-generator 1.4.4 (Kazuhiko Arase, licence MIT), copié tel quel.

**Rien n'est stocké sur le serveur.** La fiche vit dans la boîte mail de
l'association, puis dans le CRM où elle est encodée à la main. Le numéro de
membre est attribué à l'encodage. Les journaux ne contiennent ni nom ni adresse.

La page ne charge rien d'un autre site (pas de polices Google, pas de traceur).

## Réglages

Dans `www/index.html`, bloc `CONFIG` : cotisation, IBAN, titulaire du compte
(`PAYEE`), lien vers le règlement intérieur, version des clauses.

Sur le VPS, `/srv/members/.env` (modèle : `.env.example`) :

| Variable | Rôle |
|---|---|
| `RESEND_API_KEY` | Clé Resend, envoi seul, limitée à `syntonie.be`. Sans elle, l'envoi répond 503. |
| `MAIL_TO` | Destinataire des fiches |
| `MAIL_FROM` | Expéditeur |
| `ACCESS_CODE` | Code d'accueil. Vide = fiche ouverte à tous. Changer la valeur puis `docker compose up -d`. |
| `TEST_MODE` | `1` : bandeau TEST sur la page, `[TEST]` dans l'objet des e-mails |
| `CITIZENPAY_PLACE` | Lieu Citizen Pay qui reçoit la cotisation (id ou slug). Vide = pas de Citizen Pay, virement et accueil seulement. |
| `CITIZENPAY_API_URL` | API Citizen Pay. Défaut `https://api2.citizenpay.xyz` |
| `CITIZENPAY_CHECKOUT_URL` | Page de paiement Citizen Pay. Défaut `https://checkout.citizenpay.eu` |
| `FEE_CENTS` | Cotisation en centimes, défaut `2500`. Doit valoir `FEE` du bloc `CONFIG` de la page. |

`TEST_MODE` ne touche pas à Citizen Pay : les commandes et les paiements sont
réels. Pour tester sans payer pour de vrai, pointer les deux adresses vers
l'environnement de test de Citizen Pay, avec un lieu qui y existe :
`CITIZENPAY_API_URL=https://api2.staging.citizenpay.eu` et
`CITIZENPAY_CHECKOUT_URL=https://checkout.staging.citizenpay.eu`.

## Déployer

Le service tourne derrière la passerelle Caddy (`openfab-lab/syntonie-gateway`,
`caddy/sites/members.caddy`), sur le réseau Docker `gateway`, sans port publié.

```sh
rsync -a --delete --exclude .env services/inscription/ syntonie:/srv/members/
ssh syntonie 'cd /srv/members && docker compose up -d --build'
```

## Ce que ce MVP ne fait pas

Pas de base de membres, pas de numéro automatique, pas d'e-mail de
confirmation au membre, pas de suivi des renouvellements. Les paiements par
Citizen Pay sont vérifiés à l'envoi de la fiche ; les virements et les
paiements à l'accueil restent déclarés par la personne, à vérifier sur le
compte.
C'est voulu : ces points sont l'objet de l'étape suivante, à valider par le
collectif.
