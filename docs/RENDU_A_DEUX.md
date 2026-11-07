# Rendu du film 360 à deux PC

PC d'Ilyas (RTX 2060) et PC du frère (RTX 3060) rendent le film ensemble. Code: `src/partage/duo.py` (protocole),
`src/partage/duo_commandes.py` (commandes). Tests: `python tools/test_duo.py`.

## En bref

- **Temps**: le partage se règle tout seul pendant le rendu. Ilyas part du début du film, le frère de la fin. Chacun prend
  12 images à la fois et annonce ce qu'il fait. À la fin, le reste est coupé selon la vitesse mesurée de chaque PC. Les
  deux finissent à quelques minutes d'écart.
  Simulation sur le vrai film (1 710 images à calculer, 3060 supposée 1,6 fois plus rapide): environ 2,5 fois plus vite
  qu'avec le seul PC d'Ilyas, soit environ 70 h au lieu de 175 h. Le facteur 1,6 est une estimation: la vraie vitesse
  est mesurée dès le premier paquet.
- **Installation chez le frère**: rien. Un zip (code, données, Blender en même version, lanceurs), extraire, double-clic sur
  `LANCER_RENDU.bat`.
- **Mêmes images des deux côtés**: les deux PC rendent avec la même copie figée du code. Les données sont contrôlées,
  et le paquet est testé avant l'envoi (une image finale rendue avec ses seules données).
- **Suivi sur le téléphone**: application ntfy (gratuite, sans compte). Tu reçois l'avancement, la fin estimée et les
  problèmes.
- **Robuste**: un PC qu'on éteint ou qui plante ne perd rien. Relancer reprend là où il en était. Si un PC ne donne plus
  de nouvelles pendant 2 h, l'autre reprend ses images en cours. Les images noires (mémoire manquante) sont refaites
  automatiquement.
- **Montage automatique**: le PC d'Ilyas réunit les images, fait l'outro, le son et le 360. Résultat:
  `film_360_360.mp4`.

## Avant de commencer: comment les images du frère arrivent chez Ilyas

Elles font environ 1 Mo chacune (JPEG), soit à peu près 1 Go pour la part du frère.

| Choix | Réglage | Pendant le rendu | À la fin |
|---|---|---|---|
| **1. GitHub (recommandé)** | 3 min, une fois (ci-dessous) | les images arrivent toutes seules, lot par lot | rien à faire |
| 2. Dossier partagé | Google Drive pour ordinateur, OneDrive ou Dropbox déjà installé et partagé sur les deux PC (ou un dossier réseau si les deux PC sont chez toi) | automatique | rien à faire |
| 3. À la main | aucun | rien ne part | le frère envoie un seul fichier (SwissTransfer, gratuit jusqu'à 50 Go, ou clé USB). Tu le mets dans Téléchargements: ton PC le trouve et l'importe tout seul |

GitHub, réglage une fois:

1. github.com, bouton + en haut à droite, New repository. Nom `blatten-transfert`, cocher **Private** et
   « Add a README file ». Create repository.
2. Photo de profil, Settings, Developer settings, Personal access tokens, **Fine-grained tokens**, Generate new token.
   Nom `blatten-duo`, expiration 30 jours, Repository access: Only select repositories, `blatten-transfert`.
   Permissions, Repository permissions, **Contents: Read and write**. Generate token, copier le jeton (`github_pat_...`).
3. `Lancer_preparer_duo.bat` le demande (choix 1) et le garde dans `config.local.json` (jamais envoyé sur GitHub).

Ce jeton n'ouvre que le dépôt de transfert. Il voyage dans le paquet du frère sans exposer le code du film. Ne pas
utiliser le dépôt `blatten_vr` pour ça: un jeton qui peut écrire dans ce dépôt permettrait de modifier ce que lancent
les `.bat` du PC d'Ilyas.

## Étapes

### Ilyas

1. **Figer les décisions visuelles** (saturation, arbres, eau, titre, nuage...). Après le paquet, plus rien ne doit
   changer dans les images. `Lancer_preparer_duo.bat` affiche la feuille de route et demande confirmation.
2. Double-cliquer **`Lancer_preparer_duo.bat`**:
   - choix de l'envoi (1, 2 ou 3);
   - copie figée du code et paquet du frère, environ 2,5 Go et 5 à 10 min (Blender est copié une fois pour toutes);
   - **test du paquet**: une petite zone de l'image 1531 (t = 43 s) rendue avec les seules données du paquet, quelques
     minutes. S'il échoue, ne pas envoyer le paquet;
   - le dossier `D:\Blatten_render\duo\<session>` s'ouvre, avec `A_LIRE.txt` (lien des notifications compris).
3. Donner au frère `Blatten_frere_<session>.zip`: clé USB, ou swisstransfer.com (sans compte, jusqu'à 50 Go).
4. Double-cliquer **`Lancer_rendu_duo.bat`**. Pas besoin d'attendre le frère: s'il démarre plus tard, le partage s'ajuste.
5. Téléphone: application **ntfy** (Play Store, App Store), bouton +, sujet `blatten-...` écrit dans `A_LIRE.txt`
   (serveur par défaut ntfy.sh). Ou la page `https://ntfy.sh/<sujet>` dans un navigateur.

### Le frère (tout est dans `LISEZ-MOI.txt` du paquet)

1. Extraire le zip, de préférence dans `C:\` (chemin court). Il faut environ 10 Go libres.
2. Double-cliquer `LANCER_RENDU.bat`. La première fois, Blender s'installe tout seul (1 à 3 min).
3. Laisser la fenêtre ouverte (écran éteint possible: le PC ne se met pas en veille pendant le rendu).

## Pendant le rendu

- **Arrêter un PC**: fermer sa fenêtre. L'autre PC est prévenu, les images en cours redeviennent libres. Relancer le même
  `.bat` reprend sans rien perdre.
- **Arrêt programmé**: `python blatten.py duo --jusqu-a 07:00` s'arrête proprement avant 7 h. L'autre PC continue.
- **Où on en est**: `Lancer_etat_duo.bat` (Ilyas) ou `ETAT.bat` (frère): images faites par chaque PC, paquets en cours,
  vitesses, fin estimée.
- **Ne pas toucher aux données** (`prep-...`) pendant le rendu: le PC d'Ilyas s'arrêterait de lui-même, car ses images
  ne seraient plus identiques à celles du frère.
- **Windows Update**: suspendre les mises à jour une semaine sur les deux PC (Paramètres, Windows Update, Suspendre).
  Après un redémarrage imposé, il suffit de relancer le `.bat`.
- **Utiliser son PC à côté**: possible pour du léger (Blender tourne en priorité basse et laisse 2 cœurs). Pas de jeu ni
  d'application gourmande en mémoire: sous 7 Go de RAM libre, le rendu attend, et la mémoire qui manque donne des images
  noires (refaites automatiquement, mais c'est du temps perdu).

## À la fin

- Le frère a fini sa part: notification « part finie ». Avec GitHub ou un dossier partagé, tout est déjà parti. À la main,
  sa fenêtre ouvre le fichier à envoyer et SwissTransfer. Il suffit de glisser le fichier dans la page et de mettre ton
  adresse e-mail.
- Ton PC attend les dernières images du frère, les importe (téléchargées dans Téléchargements, ou dans
  `duo\<session>\apports`), recopie les images de l'intro, puis fait le montage: notification « FILM 360 PRÊT ».
- Montage à refaire plus tard (texte de l'outro changé, par exemple): `python blatten.py finir --format 360` (les images
  ne bougent pas).
- Après le rendu: révoquer le jeton GitHub (Settings, Developer settings) et supprimer la release du dépôt de transfert
  si tu veux faire de la place.

## Problèmes fréquents

| Symptôme | Cause probable | Que faire |
|---|---|---|
| « Blender ne voit aucune carte graphique » | pilote NVIDIA trop ancien | mettre à jour le pilote (application NVIDIA), redémarrer, relancer |
| Avertissement Windows (éditeur inconnu) | fichier venu d'internet | « Informations complémentaires », « Exécuter quand même » |
| « Il faut d'abord extraire le zip » | lancé depuis l'intérieur du zip | clic droit sur le zip, Extraire tout |
| « Canal de messages injoignable » | pas d'internet, ou ntfy.sh en panne | le rendu continue. Sans nouvelles l'un de l'autre, le frère s'en tient à sa part estimée et Ilyas continue tout seul |
| « Arrivée des images bloquée » (GitHub) | jeton expiré ou mal copié | refaire un jeton, relancer `Lancer_preparer_duo.bat` (nouvelle session) ou passer à l'envoi à la main (`ENVOYER_IMAGES.bat` chez le frère) |
| Ton PC attend des images du frère qui n'arrivent pas | envoi à la main pas encore fait, ou PC du frère éteint avant l'envoi | lui demander `ENVOYER_IMAGES.bat`. En dernier recours: `python blatten.py duo --tout-rendre` (ton PC refait tout ce qui manque) |
| « Les données ont changé » | une commande `prep-...` lancée pendant le rendu | remettre les données, ou refaire un paquet (nouvelle session) |
| Le frère doit recevoir un nouveau paquet | nouvelle session préparée | chaque session a son propre sujet de messages: un ancien paquet n'interfère pas, il ne sert plus |

## Comment ça marche

- **Session** (`D:\Blatten_render\duo\<session>\session.json`): plan des images (intro une image sur 2, puis toutes),
  sujet secret des messages, envoi choisi, empreinte du code figé (`code\`), liste des données.
  Les images vont dans `D:\Blatten_render\final\<date>_duo_<session>`.
- **Messages** (ntfy.sh, public, sans compte): chaque PC publie son état sur `<sujet>-etat` (images faites et en cours,
  vitesse, carte graphique). Il le fait à chaque paquet, et toutes les 45 min pendant un paquet. Les notifications
  lisibles vont sur `<sujet>`. Seules des données de rendu y passent (numéros d'images, vitesses, chemins).
- **Choix d'un paquet**: images libres les plus proches de son bout du film (ni faites, ni prises par l'autre). Taille
  12, réduite à la fin pour que les deux PC finissent ensemble, compte tenu des 3 min de préparation de scène par
  paquet. Si les deux annoncent les mêmes images au même moment, le premier arrivé les garde.
- **Lots**: chaque paquet du frère devient un zip (images + manifeste). Il part par GitHub (fichier joint d'une release
  du dépôt de transfert) ou par le dossier partagé, et il est réessayé jusqu'à ce qu'il passe. Les images rendues
  pendant une coupure sont rattrapées au redémarrage.
- **Ce qui ne peut pas être testé ici**: les `.bat` et les appels propres à Windows (veille, fermeture de fenêtre,
  dossier Téléchargements). Le reste est vérifié par `tools/test_duo.py` (simulation sur le vrai film) et par un essai
  complet avec un faux Blender: dossier partagé, envoi à la main, GitHub, PC du frère tué en cours de rendu, PC du frère
  relancé.

## Commandes

| Commande | Où | Rôle |
|---|---|---|
| `python blatten.py paquet [--transport github\|dossier\|manuel] [--sans-blender] [--sans-test] [--paquet-images 12] [--intro-pas 2]` | Ilyas | prépare la session, le paquet du frère et le teste (`Lancer_preparer_duo.bat`) |
| `python blatten.py duo [--jusqu-a HH:MM] [--tout-rendre]` | les deux | rend la part de ce PC; chez Ilyas, importe et monte (`Lancer_rendu_duo.bat`, `LANCER_RENDU.bat`) |
| `python blatten.py duo-etat` | les deux | état des deux PC (`Lancer_etat_duo.bat`, `ETAT.bat`) |
| `python blatten.py duo-envoyer` | frère | un seul zip de toutes ses images, ouvre SwissTransfer (`ENVOYER_IMAGES.bat`) |
| `python blatten.py duo-importer CHEMIN` | Ilyas | importe un zip ou un dossier d'images du frère à la main |

Option `--intro-pas 1` de `paquet`: intro rendue image par image (eau parfaitement fluide pendant les 8 s d'intro),
pour environ 120 images de plus (3 h de plus à deux).
