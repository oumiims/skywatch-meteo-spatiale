"""Collecte des éruptions solaires DONKI (NASA) vers BigQuery.

Fenêtre glissante, chargement incrémental par empreinte de ligne,
et annulation du lot en cas d'échec à mi-parcours.
"""

import hashlib
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

load_dotenv()

logger = logging.getLogger(__name__)

API_KEY = os.getenv("NASA_API_KEY")
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
DATASET_ID = "raw_donki"
TABLE_ID = "solar_flares"

URL_API_DONKI = "https://ccmc.gsfc.nasa.gov/DONKI-API/get/FLR"
JOURS_HISTORIQUE = 30      # fenêtre glissante : couvre une collecte hebdomadaire même en cas de lancement manqué
TIMEOUT_API_SECONDES = 30  # sans limite, une API qui ne répond pas bloque le pipeline entier

# Le client lit automatiquement GOOGLE_APPLICATION_CREDENTIALS depuis le .env :
# aucun chemin en dur, le script fonctionne sur n'importe quelle machine.
client = bigquery.Client(project=PROJECT_ID)
TABLE_REF = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"

# Schéma explicite : garantit que les dates arrivent en TIMESTAMP et non en texte,
# ce dont dépendent les modèles dbt. ALLOW_FIELD_ADDITION évite le plantage
# "no such field" si DONKI ajoute un jour une nouvelle colonne.
SCHEMA = [
    bigquery.SchemaField("flrid", "STRING"),
    bigquery.SchemaField("catalog", "STRING"),
    bigquery.SchemaField("instruments", "JSON"),
    bigquery.SchemaField("begintime", "TIMESTAMP"),
    bigquery.SchemaField("peaktime", "TIMESTAMP"),
    bigquery.SchemaField("endtime", "TIMESTAMP"),
    bigquery.SchemaField("classtype", "STRING"),
    bigquery.SchemaField("sourcelocation", "STRING"),
    bigquery.SchemaField("activeregionnum", "INTEGER"),
    bigquery.SchemaField("note", "STRING"),
    bigquery.SchemaField("submissiontime", "TIMESTAMP"),
    bigquery.SchemaField("versionid", "INTEGER"),
    bigquery.SchemaField("link", "STRING"),
    bigquery.SchemaField("linkedevents", "JSON"),
    bigquery.SchemaField("sentnotifications", "JSON"),
    bigquery.SchemaField("row_hash", "STRING"),
    bigquery.SchemaField("inserted_at", "TIMESTAMP"),
    bigquery.SchemaField("batch_id", "STRING"),
]


def calculer_hash(obj: dict) -> str:
    """Empreinte SHA-256 de l'intégralité des données de l'éruption.

    Hacher l'objet entier permet de détecter les révisions de la NASA
    (versionId qui passe de 1 à 2), pas seulement les nouvelles éruptions.
    sort_keys=True garantit que le même contenu donne toujours le même hash,
    y compris pour les structures imbriquées (instruments, linkedEvents).

    Args:
        obj: une éruption telle que renvoyée par l'API, sans colonne technique.

    Returns:
        L'empreinte hexadécimale de la ligne.
    """
    donnees = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(donnees.encode("utf-8")).hexdigest()


def collecter_donki() -> list:
    """Appelle l'API DONKI et renvoie les éruptions solaires de la fenêtre.

    Returns:
        La liste des éruptions, telles que renvoyées par l'API.

    Raises:
        RuntimeError: si l'API répond autre chose qu'un succès.
    """
    date_fin = date.today()
    date_debut = date_fin - timedelta(days=JOURS_HISTORIQUE)

    reponse = requests.get(
        URL_API_DONKI,
        params={
            "startDate": date_debut.isoformat(),
            "endDate": date_fin.isoformat(),
        },
        headers={"X-Api-Key": API_KEY},
        timeout=TIMEOUT_API_SECONDES,
    )

    # La clé passe par un en-tête, jamais par l'URL : on ne journalise donc
    # que le code et sa raison, sans risque d'exposer le secret.
    if not reponse.ok:
        raise RuntimeError(
            f"L'API DONKI a répondu {reponse.status_code} ({reponse.reason})."
        )

    eruptions = reponse.json()
    logger.info(
        "%d éruption(s) récupérée(s) pour la période %s -> %s.",
        len(eruptions), date_debut, date_fin,
    )
    return eruptions


def preparer_les_lignes(eruptions: list, batch_id: str) -> list:
    """Normalise les clés et ajoute les colonnes de traçabilité.

    Args:
        eruptions: les éruptions brutes issues de l'API.
        batch_id: l'identifiant de l'exécution en cours.

    Returns:
        Les lignes prêtes à être chargées.
    """
    # Normalisation en minuscules AVANT le hash : l'empreinte correspond ainsi
    # exactement aux données stockées dans BigQuery.
    lignes = [{cle.lower(): valeur for cle, valeur in ligne.items()} for ligne in eruptions]

    horodatage = datetime.now(timezone.utc).isoformat()
    for ligne in lignes:
        # Le hash est calculé avant l'ajout des colonnes techniques : sinon
        # l'horodatage entrerait dans le calcul, l'empreinte changerait à chaque
        # exécution, et aucun doublon ne serait jamais détecté.
        ligne["row_hash"] = calculer_hash(ligne)
        ligne["inserted_at"] = horodatage
        ligne["batch_id"] = batch_id

    return lignes


def recuperer_hash_existants() -> set:
    """Renvoie les empreintes déjà présentes dans la table BigQuery.

    Un set plutôt qu'une liste : la recherche d'appartenance y est immédiate,
    quel que soit le nombre de lignes déjà en base.

    Returns:
        L'ensemble des row_hash, vide si la table n'existe pas encore.
    """
    try:
        resultat = client.query(f"SELECT DISTINCT row_hash FROM `{TABLE_REF}`").result()
        return {row.row_hash for row in resultat}
    except NotFound:
        # Premier lancement : la table n'existe pas, tout est donc nouveau.
        # On n'attrape que NotFound : une erreur de permission ou de nom de
        # table doit remonter, pas être confondue avec une table vide.
        logger.info("Table %s absente : premier chargement.", TABLE_REF)
        return set()


def charger_les_lignes(lignes: list) -> int:
    """Insère les lignes dans la table brute.

    Args:
        lignes: les lignes préparées, colonnes techniques comprises.

    Returns:
        Le nombre de lignes insérées.
    """
    job_config = bigquery.LoadJobConfig(
        schema=SCHEMA,
        write_disposition="WRITE_APPEND",
        schema_update_options=["ALLOW_FIELD_ADDITION"],
    )
    client.load_table_from_json(lignes, TABLE_REF, job_config=job_config).result()
    logger.info("%d ligne(s) ajoutée(s) dans %s.", len(lignes), TABLE_REF)
    return len(lignes)


def annuler_le_lot(batch_id: str) -> None:
    """Supprime toutes les lignes insérées par cette exécution.

    C'est le rollback de ce pipeline. Le mot-clé ROLLBACK n'y figure pas :
    un chargement BigQuery est un load job, pas du SQL, il ne peut donc pas
    entrer dans une transaction. Le batch_id joue le rôle de mémoire de ce
    qu'il faut défaire, et la suppression fait le reste.

    Args:
        batch_id: l'identifiant du lot à annuler.
    """
    requete = f"DELETE FROM `{TABLE_REF}` WHERE batch_id = @batch_id"
    # Requête paramétrée : la valeur est transmise à part et toujours traitée
    # comme une donnée, jamais comme du code.
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id)
        ]
    )
    try:
        client.query(requete, job_config=job_config).result()
        logger.warning("Lot %s supprimé : la table est revenue à son état initial.", batch_id)
    except Exception:
        # Le rollback ne doit jamais masquer l'erreur qui l'a déclenché : si la
        # table ou la colonne batch_id n'existe pas encore, c'est qu'aucune ligne
        # n'a été insérée, donc il n'y a rien à annuler. On le signale sans
        # interrompre, et l'erreur d'origine reste celle qui remonte.
        logger.warning("Aucun lot à annuler dans %s (table ou colonne absente).", TABLE_REF)


def ingerer_donki() -> None:
    """Enchaîne la collecte et le chargement, et annule le lot en cas d'échec.

    Raises:
        Exception: toute erreur survenue pendant l'ingestion, relancée après
            l'annulation du lot.
    """
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    logger.info("Début de l'ingestion DONKI, lot %s.", batch_id)

    try:
        eruptions = collecter_donki()
        lignes = preparer_les_lignes(eruptions, batch_id)

        hash_existants = recuperer_hash_existants()
        a_charger = [ligne for ligne in lignes if ligne["row_hash"] not in hash_existants]
        logger.info(
            "%d nouvelle(s) ligne(s) à ajouter sur %d récupérée(s).",
            len(a_charger), len(lignes),
        )

        if a_charger:
            charger_les_lignes(a_charger)
        else:
            logger.info("Aucune nouvelle ligne : les données sont déjà à jour.")

        logger.info("Ingestion terminée, lot %s.", batch_id)

    except Exception:
        # Seul cas où attraper largement est justifié : on veut nettoyer quoi
        # qu'il arrive. Rien n'est avalé — on journalise, puis on relance.
        logger.exception("Ingestion interrompue, annulation du lot %s.", batch_id)
        annuler_le_lot(batch_id)
        # Sans ce raise, le script se terminerait normalement et
        # l'orchestrateur afficherait un succès sur une exécution échouée.
        raise


def main() -> None:
    """Point d'entrée : règle la journalisation puis lance l'ingestion."""
    # Journalisation en console : sur une machine jetable (GitHub Actions),
    # un fichier disparaîtrait avec la machine, alors que la sortie standard
    # est conservée dans l'historique d'exécution.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    ingerer_donki()


if __name__ == "__main__":
    main()