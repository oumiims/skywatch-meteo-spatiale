"""Collecte des événements de météo spatiale NOAA SWPC vers BigQuery.

Chargement incrémental par empreinte de ligne, et annulation du lot
en cas d'échec à mi-parcours.
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

load_dotenv()

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
DATASET_ID = "raw_noaa"
TABLE_ID = "raw_noaa_events"

# Un seul flux collecté : edited_events. Les autres flux NOAA (solar_regions,
# sunspot_report, solar_probabilities) ont un grain différent — une tache solaire
# n'est pas un événement daté — et feront l'objet de tables dédiées si besoin.
URL_FLUX_NOAA = "https://services.swpc.noaa.gov/json/edited_events.json"
TIMEOUT_API_SECONDES = 30  # sans limite, un service qui ne répond pas bloque le pipeline entier

# Le client lit automatiquement GOOGLE_APPLICATION_CREDENTIALS depuis le .env :
# aucun chemin en dur, le script fonctionne sur n'importe quelle machine.
client = bigquery.Client(project=PROJECT_ID)
TABLE_REF = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"

# Schéma explicite : les dates en TIMESTAMP pour dbt. Les champs "particulars"
# restent en STRING car leur signification dépend du type d'événement.
SCHEMA = [
    bigquery.SchemaField("begin_datetime", "TIMESTAMP"),
    bigquery.SchemaField("begin_quality", "STRING"),
    bigquery.SchemaField("max_datetime", "TIMESTAMP"),
    bigquery.SchemaField("max_quality", "STRING"),
    bigquery.SchemaField("end_datetime", "TIMESTAMP"),
    bigquery.SchemaField("end_quality", "STRING"),
    bigquery.SchemaField("observatory", "STRING"),
    bigquery.SchemaField("quality", "STRING"),
    bigquery.SchemaField("type", "STRING"),
    bigquery.SchemaField("coded_type", "INTEGER"),
    bigquery.SchemaField("obsid", "INTEGER"),
    bigquery.SchemaField("location", "STRING"),
    bigquery.SchemaField("frequency", "STRING"),
    bigquery.SchemaField("particulars1", "STRING"),
    bigquery.SchemaField("particulars2", "STRING"),
    bigquery.SchemaField("particulars3", "STRING"),
    bigquery.SchemaField("particulars4", "STRING"),
    bigquery.SchemaField("particulars5", "STRING"),
    bigquery.SchemaField("particulars6", "STRING"),
    bigquery.SchemaField("particulars7", "STRING"),
    bigquery.SchemaField("particulars8", "STRING"),
    bigquery.SchemaField("particulars9", "STRING"),
    bigquery.SchemaField("particulars10", "STRING"),
    bigquery.SchemaField("region", "INTEGER"),
    bigquery.SchemaField("bin", "INTEGER"),
    bigquery.SchemaField("age", "INTEGER"),
    bigquery.SchemaField("status_code", "INTEGER"),
    bigquery.SchemaField("status_text", "STRING"),
    bigquery.SchemaField("change_flag", "INTEGER"),
    bigquery.SchemaField("row_hash", "STRING"),
    bigquery.SchemaField("inserted_at", "TIMESTAMP"),
    bigquery.SchemaField("batch_id", "STRING"),
]


def calculer_hash(obj: dict) -> str:
    """Empreinte SHA-256 de l'intégralité des données de l'événement.

    NOAA ne fournit aucun identifiant unique : le hash sert donc à la fois
    d'empreinte de contenu et de clé technique de la ligne. Il capture aussi
    les révisions, NOAA corrigeant ses observations a posteriori.
    sort_keys=True garantit que le même contenu donne toujours le même hash.

    Args:
        obj: un événement tel que renvoyé par le flux, sans colonne technique.

    Returns:
        L'empreinte hexadécimale de la ligne.
    """
    donnees = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(donnees.encode("utf-8")).hexdigest()


def collecter_noaa() -> list:
    """Appelle le flux NOAA SWPC et renvoie les événements observés.

    Le flux n'accepte pas de paramètres de dates : NOAA publie une fenêtre
    glissante d'environ 30 jours. La déduplication par hash gère le recouvrement
    d'une exécution à l'autre.

    Returns:
        La liste des événements, tels que renvoyés par le flux.

    Raises:
        RuntimeError: si le service répond autre chose qu'un succès.
    """
    reponse = requests.get(URL_FLUX_NOAA, timeout=TIMEOUT_API_SECONDES)

    if not reponse.ok:
        raise RuntimeError(
            f"Le flux NOAA a répondu {reponse.status_code} ({reponse.reason})."
        )

    evenements = reponse.json()
    logger.info("%d événement(s) récupéré(s) depuis NOAA SWPC.", len(evenements))
    return evenements


def preparer_les_lignes(evenements: list, batch_id: str) -> list:
    """Normalise les clés et ajoute les colonnes de traçabilité.

    Args:
        evenements: les événements bruts issus du flux.
        batch_id: l'identifiant de l'exécution en cours.

    Returns:
        Les lignes prêtes à être chargées.
    """
    # Normalisation en minuscules AVANT le hash : l'empreinte correspond ainsi
    # exactement aux données stockées dans BigQuery.
    lignes = [{cle.lower(): valeur for cle, valeur in ligne.items()} for ligne in evenements]

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


def ingerer_noaa() -> None:
    """Enchaîne la collecte et le chargement, et annule le lot en cas d'échec.

    Raises:
        Exception: toute erreur survenue pendant l'ingestion, relancée après
            l'annulation du lot.
    """
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    logger.info("Début de l'ingestion NOAA, lot %s.", batch_id)

    try:
        evenements = collecter_noaa()
        lignes = preparer_les_lignes(evenements, batch_id)

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
    ingerer_noaa()


if __name__ == "__main__":
    main()