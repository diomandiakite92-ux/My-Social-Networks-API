# My Social Networks API

API REST développée avec FastAPI pour gérer des utilisateurs, événements, groupes et leurs services associés. La persistance locale utilise SQLite.

## Démarrer

```powershell
uv sync
uv run my-social-networks-api
```

L’API écoute sur `http://127.0.0.1:8000`. La documentation OpenAPI interactive est disponible sur `/docs`, la documentation alternative sur `/redoc` et le contrôle de disponibilité sur `/health`.

La base est créée au premier démarrage dans `data/social_networks.sqlite3`. Pour utiliser un autre emplacement, définissez `SOCIAL_API_DB` avant de démarrer l’application.

## Services

| Domaine | Routes principales |
|---|---|
| Utilisateurs | `/users`, `/users/{user_id}` |
| Événements, participants et organisateurs | `/events`, `/events/{event_id}`, `/events/{event_id}/participants`, `/events/{event_id}/organizers` |
| Groupes et membres | `/groups`, `/groups/{group_id}`, `/groups/{group_id}/members/{user_id}` |
| Discussions | `/events/{event_id}/discussion`, `/groups/{group_id}/discussion`, `/threads/{thread_id}/messages`, `/messages/{message_id}/comments` |
| Albums et photos | `/events/{event_id}/albums`, `/albums/{album_id}/photos`, `/photos/{photo_id}/comments` |
| Sondages | `/events/{event_id}/polls`, `/polls/{poll_id}/responses`, `/polls/{poll_id}/results` |
| Billetterie | `/events/{event_id}/ticket-types`, `/events/{event_id}/ticket-types/{ticket_type_id}/tickets` |
| Liste d’achats | `/events/{event_id}/shopping-items` |
| Covoiturage bonus | `/events/{event_id}/rides` |

Les ressources principales offrent les opérations de création, lecture, mise à jour et suppression adaptées. Les fils de discussion sont créés automatiquement avec leur événement ou leur groupe. Les listes acceptent la pagination ; les utilisateurs, événements et groupes acceptent aussi une recherche par `search`.

## Règles appliquées

- Les e-mails sont normalisés en minuscules et uniques.
- Le créateur d’un événement devient automatiquement organisateur. Un événement conserve toujours au moins un organisateur ; sa date de fin doit être postérieure à sa date de début.
- Lorsqu’un événement est créé dans un groupe, le créateur doit être administrateur ou disposer du droit de création. Les membres du groupe sont ajoutés aux participants de l’événement.
- Un événement privé n’est visible que par ses organisateurs et participants. Un groupe privé peut être découvert par son nom et ses images, mais ses détails et ses membres sont réservés aux membres ; un groupe secret est caché aux non-membres.
- Le créateur d’un groupe devient son premier administrateur. Il doit toujours rester au moins un administrateur.
- Un fil de discussion est créé avec son événement ou son groupe et ne peut être associé qu’à l’un des deux.
- Seuls les participants peuvent publier ou commenter des photos et répondre aux sondages. Chaque réponse à un sondage contient un choix pour chacune de ses questions ; une réponse existante peut être modifiée.
- La billetterie est réservée aux événements publics. Les montants sont exprimés en centimes, le stock ne peut pas devenir négatif et une adresse e-mail ne peut obtenir qu’un billet par événement.
- La liste d’achats et le covoiturage sont désactivés par défaut pour chaque événement. Un article porte un nom unique par événement, sans distinction de casse ; une tentative de doublon renvoie un conflit.
- Une offre de covoiturage part avant le début de l’événement. Elle décrit les places disponibles, mais ne réserve pas encore les sièges des passagers.
- Les images sont référencées par URL ; aucun stockage de fichiers ni paiement en ligne n’est inclus.

Les dates sans fuseau horaire sont interprétées en UTC puis enregistrées en UTC.

## Identité et autorisations

L’énoncé ne définit ni connexion, ni jetons d’accès. Les routes qui nécessitent une identité utilisent donc des identifiants (`creator_id`, `viewer_id`, `actor_id`, etc.) dans le corps ou la query string pour rendre les règles métier démontrables. Ces identifiants ne prouvent pas l’identité de l’appelant et ne remplacent pas une authentification ; il faudra ajouter celle-ci avant une mise en production réelle.

## Postman

La collection locale `postman_collection.json` regroupe les requêtes et explications des principaux services. Importez-la dans Postman et définissez sa variable `baseUrl` à `http://127.0.0.1:8000`.

Documentation publique : [My Social Networks API — Documentation des endpoints](https://documenter.getpostman.com/view/51149644/2sBYHbrbgD).
