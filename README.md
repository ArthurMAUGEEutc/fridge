# FridgeTracker

Gestion des dates de péremption des produits du frigo via scan de code-barres.

## Lancer le serveur

### 1. Cloner le repo

```bash
git clone https://github.com/ArthurMAUGEEutc/fridge.git
cd fridge
```

### 2. Générer le certificat HTTPS (une seule fois)

La caméra iPhone nécessite HTTPS. Génère un certificat auto-signé :

```bash
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=localhost"
```

### 3. Lancer le serveur

```bash
python3 server.py
```

Le terminal affiche l'adresse à ouvrir sur le téléphone :

```
FridgeTracker running on:
  Local  → https://localhost:8000
  Réseau → https://192.168.x.x:8000
  DB     → /chemin/vers/fridge.db
```

### 4. Ouvrir sur iPhone

1. iPhone et Mac doivent être sur le **même réseau Wi-Fi**
2. Ouvre Safari sur l'iPhone et tape l'adresse **Réseau** affichée
3. Safari affiche un avertissement "connexion non sécurisée" → **Afficher les détails → Visiter le site web**
4. La caméra démarre automatiquement

## Utilisation

| Vue | Description |
|-----|-------------|
| **Scanner** | Scanne un code-barres → enrichissement automatique → saisie de la date de péremption → ajout au frigo |
| **Mon Frigo** | Liste de tous les produits triés par date, avec boutons "Ouvert" et "Jeté" |
| **Alertes** | Produits qui expirent dans moins de 3 jours ou déjà périmés |

## Prérequis

- Python 3.9+
- `openssl` (installé par défaut sur macOS)
- Aucune dépendance externe — stdlib uniquement
