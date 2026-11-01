"""Collecte historique des éruptions solaires DONKI, année par année.

Script ponctuel, à lancer une seule fois pour constituer la profondeur
historique. La collecte courante reste assurée par collecte_donki.py, dont
ce script réutilise les fonctions plutôt que de les dupliquer.

Découpage par année : une requête sur onze ans ferait tomber l'API en timeout.
C'est aussi ce qui rend le rollback utile — plusieurs insertions successives,
donc un échec possible à mi-parcours.

Lancer depuis ce dossier : cd collecte/donki && python collecte_donki_historique.py
"""

import logging
import time
from datetime import date, datetime, timezone

import requests

from collecte_donki import (
    API_KEY,
    TIMEOUT_API_SECONDES,
    URL_API_DONKI,
    annuler_le_lot,
    charger_les_lignes,
    preparer_les_lignes,
    recuperer_hash_existants,
)

logger = logging.getLogger(__name__)

ANNEE_DEBUT = 2015           # proche du maximum du cycle solaire 24
ANNEE_FIN = 2026             # cycle 25 : la fenêtre couvre deux maxima et un minimum
PAUSE_ENTRE_APPELS = 0.5     # ménage l'API, qui répond mal en période de charge


def collecter_une_annee(annee: int) -> list:
    """Appelle l'API DONKI sur une année complète.

    Args:
        annee: l'année à collecter.

    Returns:
        La liste des éruptions de cette année.

    Raises:
        RuntimeError: si l'API répond autre chose qu'un succès.
    """
    reponse = requests.get(
        URL_API_DONKI,
        params={
            "startDate": date(annee, 1, 1).isoformat(),
            "endDate": date(annee, 12, 31).isoformat(),
        },
        headers={"X-Api-Key": API_KEY},
        timeout=TIMEOUT_API_SECONDES,
    )

    if not reponse.ok:
        raise RuntimeError(
            f"L'API DONKI a répondu {reponse.status_code} ({reponse.reason}) pour {annee}."
        )

    eruptions = reponse.json()
    logger.info("%d : %d éruption(s) récupérée(s).", annee, len(eruptions))
    return eruptions


def collecter_historique() -> None:
    """Parcourt chaque année de la période et charge ce qui est nouveau.

    Raises:
        Exception: toute erreur survenue pendant la collecte, relancée après
            l'annulation du lot.
    """
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    logger.info(
        "Début de la collecte historique DONKI %d-%d, lot %s.",
        ANNEE_DEBUT, ANNEE_FIN, batch_id,
    )

    total_charge = 0

    try:
        for annee in range(ANNEE_DEBUT, ANNEE_FIN + 1):
            eruptions = collecter_une_annee(annee)
            if not eruptions:
                continue

            lignes = preparer_les_lignes(eruptions, batch_id)

            # Les empreintes sont relues à chaque année : le chargement de
            # l'année précédente en a ajouté, et les ignorer créerait des doublons.
            hash_existants = recuperer_hash_existants()
            a_charger = [l for l in lignes if l["row_hash"] not in hash_existants]

            if a_charger:
                total_charge += charger_les_lignes(a_charger)
            else:
                logger.info("%d : aucune nouvelle ligne.", annee)

            time.sleep(PAUSE_ENTRE_APPELS)

        logger.info(
            "Collecte historique terminée : %d ligne(s) ajoutée(s) au total, lot %s.",
            total_charge, batch_id,
        )

    except Exception:
        # Onze insertions successives : un échec en cours de route laisserait
        # une partie des années en base. Le rollback annule le lot entier.
        logger.exception("Collecte historique interrompue, annulation du lot %s.", batch_id)
        annuler_le_lot(batch_id)
        raise


def main() -> None:
    """Point d'entrée : règle la journalisation puis lance la collecte."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    collecter_historique()


if __name__ == "__main__":
    main()