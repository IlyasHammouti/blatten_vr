# Rendu final sur deux PC, sans le protocole duo (19 nov. 2026)

Situation : le rendu final_v1 tourne déjà sur le PC de Samy (RTX 3060 12 Go), image 1 vers 1525. Le PC d'Ilyas (RTX 2060 6 Go, environ 1,6 fois plus lent, carte trop petite pour la poussière du bout) l'aide en partant de l'image 950 et en remontant (`--inverse`).

- Les images sont indépendantes : `--origine 1` fixe le temps de simulation de chaque paquet, donc l'ordre de rendu ne change pas l'image.
- Conditions pour des images identiques : même code (empreinte_code), mêmes données (cache), même Blender 5.2.2 LTS. Contrôle : `python tools/verifier_donnees.py`.
- Samy ne saute que les images qu'il a sur son disque : les images rendues par le PC d'Ilyas doivent lui être envoyées (zip, Google Drive) avant qu'il reprenne au-dessus de 950, ou alors Samy reprend directement avec `--de 951` (ligne de nuit/file.txt) et le zip arrive après.
- Jonction : ARRET.txt sur les deux PC dès qu'ils sont à moins de ~40 images. Plan : Ilyas rend 950 vers X, Samy rend 1 vers X-1 puis 951 vers 1525.
- Montage final (`finir` : outro, AmbiX, assemblage, métadonnées 360) : sur Samy, seulement sur ordre d'Ilyas, quand 1525 images sont présentes.
- Poids : environ 1,6 Mo par image, film complet environ 2,4 Go, part du PC d'Ilyas environ 0,5 à 1 Go.
- Prompt de la conversation du PC d'Ilyas : docs/PROMPT_PC_ILYAS.md.
