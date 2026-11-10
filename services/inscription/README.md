# Inscription des membres — MVP (la fiche part par e-mail)

En ligne sur <https://members.syntonie.be>, en mode test.

- `www/index.html` : la fiche, FR / NL / EN, en trois écrans : la fiche, la
  cotisation (QR de virement SEPA, 25 €, communication
  `Cotisation <année> <Nom> <Prénom>`), la confirmation.
- `app.py` : sert la page, valide la fiche et l'envoie à `contact@syntonie.be`
  via Resend. Python seul, aucune dépendance.

Deux garde-fous, nés de l'expérience (des inscriptions en ligne jamais payées
s'ajoutaient à la liste des membres) :

- **Un code d'accueil** (`ACCESS_CODE`) est demandé en tête de fiche. Un·e
  bénévole le donne sur place : on ne s'inscrit pas sans venir à l'atelier.
- **Rien n'est envoyé avant le paiement déclaré.** La fiche part quand la
  personne clique « J'ai fait le virement » ou « J'ai payé à l'accueil ».
  L'e-mail dit lequel. Qui s'arrête au QR ne laisse aucune trace.
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

## Déployer

Le service tourne derrière la passerelle Caddy (`openfab-lab/syntonie-gateway`,
`caddy/sites/members.caddy`), sur le réseau Docker `gateway`, sans port publié.

```sh
rsync -a --delete --exclude .env services/inscription/ syntonie:/srv/members/
ssh syntonie 'cd /srv/members && docker compose up -d --build'
```

## Ce que ce MVP ne fait pas

Pas de base de membres, pas de numéro automatique, pas d'e-mail de
confirmation au membre, pas de suivi des paiements ni des renouvellements.
C'est voulu : ces points sont l'objet de l'étape suivante, à valider par le
collectif.
