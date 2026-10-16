# Compatibilité des e-mails HTML et gabarits Bulletproof (Outlook Web & Desktop)

## Contexte
Lors de la campagne d'envoi de l'Annonce pour l'Édition 2026, des anomalies de rendu majeures ont été constatées sur `outlook.live.com` (Outlook Web) ainsi que sur les clients de messagerie stricts :
1. **En-tête festif** : L'utilisation exclusive de la propriété CSS `background: linear-gradient(...)` a conduit le moteur de rendu d'Outlook à ignorer la directive. En l'absence de couleur de fond unie de repli (`background-color` ou attribut HTML `bgcolor`), la cellule d'en-tête est devenue blanche, rendant le titre principal `<h1>` (`color: #ffffff`) invisible et le sous-titre rose clair (`#fecaca`) quasi illisible par manque de contraste.
2. **Bouton CTA Espace Lutin** : Le lien hypertexte stylisé avec `display: inline-block`, `background: linear-gradient(...)` et `color: #ffffff` a perdu son fond sur Outlook, affichant du texte blanc sur fond blanc (invisible), seul le glyphe emoji `👉` restant apparent.
3. **Mode sombre (Dark Mode)** : Les clients de messagerie récents réinterprètent agressivement les couleurs sans balisage dual-scheme explicite.

## Décision
1. **Fallback de couleur systématique sur les dégradés** : Toute cellule ou conteneur utilisant un dégradé CSS (`linear-gradient`) doit obligatoirement déclarer au préalable un attribut HTML `bgcolor` solide ainsi qu'une propriété CSS `background-color` (ex. `#991b1b` pour l'en-tête, `#dc2626` pour le bouton CTA).
2. **Architecture de bouton Table-Button « Bulletproof »** : Pour éliminer les limitations de rendu d'Outlook (qui ignore les paddings sur les balises `<a>`), le bouton d'appel à l'action est encapsulé dans une table HTML dédiée `<table role="presentation" border="0" cellspacing="0" cellpadding="0" align="center">`. Le `<td>` porte la couleur de fond et le rayon de courbure, tandis que la balise `<a>` conserve un texte blanc contrasté (`color: #ffffff !important;` ou explicite) et une surface cliquable étendue.
3. **Support du mode sombre (Dual-Scheme)** : Intégration systématique des balises `<meta name="color-scheme" content="light dark">` et `<meta name="supported-color-schemes" content="light dark">` dans l'en-tête `<head>` de tous les gabarits d'e-mails pour empêcher les inversions de contraste inattendues.
4. **Périmètre d'application** : Ces règles s'appliquent immédiatement au gabarit par défaut `DEFAULT_ANNONCE_TEMPLATE` dans `source/pere_noel_fremo/gabarits.py`, au fichier de ressource `res/2026/annonce.txt`, et serviront de standard pour tout nouveau courriel du projet.
