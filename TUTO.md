# TUTO : comprendre le projet et installer ton poste

Ce fichier est fait pour être **collé tel quel à ChatGPT** (ou Claude). Il explique le projet simplement, puis guide l'installation
jusqu'au benchmark. Ensuite tu peux poser toutes les questions de détail à l'IA.

## Consigne pour l'IA (à lire en premier)

Tu aides Maxime, étudiant en géographie, à installer et comprendre ce projet. Il n'est pas forcément à l'aise avec le code.

- Parle français, simplement, sans jargon non expliqué. Sois bref.
- Guide-le **une étape à la fois**. Après chaque étape, demande-lui ce qu'il voit (ou le message d'erreur complet) avant de passer à la suivante.
- Si une étape échoue, demande-lui de copier le message d'erreur en entier, puis aide à le comprendre. Ne devine pas : dis ce qui te manque.
- Quand il demande de t'expliquer le projet, réponds à partir de ce fichier, du `README.md`, de `docs/ARCHITECTURE.md` et de `docs/CONTRAT_MATIERE.md` s'il te les a donnés. Si tu ne sais pas, dis-le.
- Les décisions de `docs/CONTRAT_MATIERE.md` sont des décisions du groupe, pas des interdits. Si une idée y va à l'encontre, dis-lui de contacter Ilyas avant.
- Ne lui fais pas modifier `config.json`, `camera.json` ni `src/scene/` : ce sont des fichiers partagés.

## 1. Le projet en deux minutes

On fait une **vidéo immersive à 360°** de l'avalanche de roche et de glace de **Blatten** (Suisse, 28 mai 2025, effondrement à 15 h 24).
Elle sera vue sur smartphone via YouTube (QR code) lors du colloque « Mouvements de terrain : aléas et réponses des sociétés »,
CNRS Thiais, 3 et 4 décembre 2026. Premier rendu à remettre le **25 novembre 2026**. Durée : environ 1 minute, dont 40 s d'événement.

Les ingrédients :
1. **La simulation** de Johan Gaume : 202 fichiers `.ply`, un par seconde, 1,17 million de particules chacun. C'est la matière qui dévale.
2. **L'environnement** (fait par Ilyas) : relief et image aérienne de swisstopo, calés sur la simulation, ciel couvert, brume.
3. **Blender** : le logiciel qui assemble tout et fait le rendu image par image (environ 2 minutes par image, des milliers d'images, d'où les deux PC).
4. **Le son** spatialisé, ajouté plus tard.

Les rôles : Ilyas fait l'environnement et la caméra. **Maxime fait la matière** (à quoi ressemblent l'avalanche, le dépôt, la poussière).
Leurs deux approches seront fusionnées plus tard.

Le dépôt GitHub contient **le code et les réglages**. Les gros fichiers (relief, simulation) n'y sont pas, ils se partagent à part.

Un seul programme à connaître : **`blatten.py`**. Il lance tout (installation, préparation des données, benchmark, rendu).
Si on le lance sans rien, il affiche un **menu**.

## 2. Ce qu'il te faut avant de commencer

| Quoi | Taille | D'où |
|---|---|---|
| Un ordinateur Windows avec ~20 Go libres | | |
| Les 202 PLY de Johan (fichier wetransfer) | 6,2 Go | ton wetransfer, à dézipper |
| `cache_ilyas.zip` : l'environnement déjà préparé (terrain, relief, image aérienne) | ~0,6 Go | **Ilyas te le donne** |
| `Nesthorn_release_klein.vdb` (zone de départ, facultatif) | 6 Mo | Ilyas |

Pas nécessaire au début : le fichier de terrain de 3,6 Go et le téléchargement swisstopo (`download`). Le zip d'Ilyas les remplace.
Les listes d'URL swisstopo (CSV) sont déjà dans le dépôt.

## 3. Installer les logiciels

1. **Blender 5.2 LTS** : blender.org, installateur Windows. Noter où est `blender.exe`.
2. **Python 3.8 ou plus** : python.org. À l'installation, **cocher « Add python.exe to PATH »**.
3. **Git** : git-scm.com, installation par défaut.
4. Un compte GitHub accepté comme collaborateur du dépôt `IlyasHammouti/blatten_vr` (invitation reçue par e-mail).

Vérification : ouvrir l'invite de commandes (touche Windows, taper `cmd`, Entrée) et lancer `python --version` puis `git --version`.
Les deux doivent afficher un numéro de version.

## 4. Récupérer le projet

**Pas dans OneDrive ni Dropbox** (ils abîment les gros fichiers et le dossier `.git`). Exemple avec `C:\Dev` :

```
mkdir C:\Dev
cd C:\Dev
git clone https://github.com/IlyasHammouti/blatten_vr.git blatten-vr
cd blatten-vr
```

Git peut demander de te connecter à GitHub : accepter la fenêtre de connexion.

## 5. Régler le chemin de ta machine

Dans le dossier `blatten-vr`, copier `config.local.example.json` en `config.local.json`, puis l'ouvrir avec le Bloc-notes et adapter :

```
{
  "blender": "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe",
  "data_root": "D:/Blatten",
  "cache_dir": "D:/Blatten/pipeline/cache",
  "swisstopo_dir": "D:/Blatten/swisstopo",
  "johan_dir": "D:/Blatten/Data_Johan"
}
```

- Mettre des barres `/` (pas `\`).
- Choisir un disque avec au moins 20 Go libres.
- Ce fichier est propre à ta machine : il n'est jamais envoyé sur GitHub.

## 6. Vérifier l'installation

```
python blatten.py setup
python blatten.py status
```

`setup` retrouve Blender, installe deux petites bibliothèques et crée les dossiers. `status` dit ce qui est prêt et ce qui manque.
À ce stade, seules les données doivent manquer. On peut aussi **double-cliquer sur `blatten.py`** : un menu s'ouvre, et la fenêtre
attend la touche Entrée avant de se fermer, ce qui laisse lire les erreurs.

## 7. Mettre les données en place

1. **Cache d'Ilyas** : dézipper `cache_ilyas.zip` **dans** le dossier `cache_dir` de ta config. On doit voir directement `env`,
   `Terrain_mesh_8m.blend`, `meta.json`... (pas un dossier de plus).
2. **PLY de Johan** : dézipper le wetransfer, par exemple dans `D:/Blatten/Data_Johan/ply_202/`. Il doit y avoir 202 fichiers `.ply`.
3. **VDB de départ** (facultatif) : copier `Nesthorn_release_klein.vdb` dans `johan_dir`.

Relancer `python blatten.py status` : l'environnement doit être signalé prêt.

**Haute résolution autour de la caméra (facultatif, recommandé pour la version finale)**

1. `python blatten.py download --dry-run` (taille), puis `python blatten.py download` : récupère aussi swissALTI3D 0,5 m, SWISSIMAGE 10 cm et swissBUILDINGS3D v2 (listes dans `data_sources/swisstopo/`).
2. `python blatten.py prep-env --hires` : fabrique `dem_05m.npy` et les patchs d'ortho fine.
3. `python blatten.py visible --eye 1.7 --ecrire-camera` : calcule la zone visible depuis la caméra (sans limite de distance), l'enregistre à part
   dans `<cache>/env/visible/` (rien n'est supprimé) et place la caméra à 1,70 m du sol. Ensuite `--cull` dans la scène ne garde que cette zone.

## 8. Convertir les PLY de Johan (attention)

Le cache d'Ilyas contient un `meta.json` qui vient d'**un ancien fichier unique**. Convertir les 202 nouveaux dedans mélangerait les données.
Deux règles :
- Le **repère** ne change pas. Origine imposée : `1117.4016956592827 0 -1121.1231332002285` (repère de Johan, Y vertical).
- Écrire dans un **autre dossier de sortie**.

Essai rapide (un fichier sur dix, donc 21 fichiers) :

```
python blatten.py prep-particules D:/Blatten/Data_Johan/ply_202 --out D:/Blatten/pipeline/cache_ply202 --stride 10 --every 10 --reset --origin 1117.4016956592827 0 -1121.1231332002285
```

Chaque PLY a 1 168 808 particules, `--stride 10` en garde une sur dix. Pour tout convertir, enlever `--every 10` (plus long).
Ne jamais mettre les `.npy` dans git. Le choix définitif du stride se fera avec les tests de rendu.

## 9. Le benchmark

```
python blatten.py bench
```

Il mesure la vitesse de rendu de **ta** machine avec les mêmes réglages que ceux d'Ilyas, pour pouvoir les comparer.
Compter 20 à 40 minutes, sans toucher à l'ordinateur. Il crée un fichier JSON et une image dans `bench_results/`.

Pour l'envoyer au groupe :

```
git checkout -b maxime/bench
git add bench_results/*.json
git commit -m "Benchmark machine de Maxime"
git push -u origin maxime/bench
```

Puis prévenir Ilyas. `python blatten.py bench-compare` affiche le tableau des machines (il signale celles qui ne sont pas comparables).

## 10. Test grandeur nature : 3 secondes de l'événement

À faire après le benchmark. Il rend **3 secondes réelles de l'avalanche** (secondes 50 à 53 de la simulation) dans l'environnement,
avec les vrais fichiers de Johan, pour juger l'aspect et mesurer le temps réel.

```
python blatten.py test-clip
```

Le programme convertit 4 PLY (dans `cache_dir/clip/`), puis produit dans `render/test_clip/` :
- 4 images 3840x1920 avec 24, 48, 96 et 192 échantillons (pour choisir le bon compromis qualité / temps),
- un clip de 3 s en demi-résolution, image par image (`clip_apercu.mp4`, ou le dossier `clip/` si ffmpeg manque). La version `clip_apercu_360.mp4` contient les métadonnées 360 : c'est celle à ouvrir dans VLC (glisser la souris pour tourner) ou à envoyer sur YouTube. Pour une autre vidéo : `python blatten.py meta360 fichier.mp4`,
- un JSON de temps dans `bench_results/clip_<machine>_<date>.json`, à pousser sur GitHub comme le benchmark.

Durée : environ 2 h 30 sur un PC comme celui d'Ilyas (le clip prend l'essentiel). On peut interrompre et relancer la même commande :
les images du clip déjà rendues sont conservées. Pour un essai rapide : `python blatten.py test-clip --every 3` (une image sur trois).

Limites : caméra provisoire, particules en sphères, relief à 2 m. C'est un test de temps et d'aspect, pas une image finale.
Pour que la vidéo se monte, installer ffmpeg (`winget install ffmpeg` dans une invite de commandes), sinon seules les images sont produites.

## 11. Ensuite : la matière

Une fois le benchmark fait, ton travail est dans `src/matiere/`. Lire `docs/CONTRAT_MATIERE.md` (les décisions déjà prises) et
donner `docs/HANDOVER_IA_MATIERE.md` à ton IA pour qu'elle t'aide à coder cette partie. Travailler sur une branche `maxime/...`.

## En cas de blocage

1. Copier le message d'erreur **complet** (la fenêtre reste ouverte jusqu'à Entrée).
2. Le donner à l'IA avec l'étape où tu en es.
3. Si l'IA ne trouve pas, l'envoyer à Ilyas.

Erreurs fréquentes : `python` non reconnu (Python pas dans le PATH, le réinstaller en cochant la case), chemin avec `\` au lieu de `/` dans
`config.local.json`, cache dézippé un niveau trop bas, Blender introuvable (vérifier le chemin dans `config.local.json`).
