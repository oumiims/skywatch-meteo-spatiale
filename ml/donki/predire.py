"""
Prediction de l'association a un CME (source DONKI).

Lit la table de features produite par dbt, applique le modele entraine, et
ecrit le resultat dans ml.donki_predictions. C'est cette table que le tableau
de bord lira : le modele ne tourne jamais dans l'outil de visualisation.

Regle a ne jamais enfreindre : on predit sur la table de features propre,
jamais sur les donnees brutes. Le modele doit recevoir exactement la meme
donnee preparee qu'a l'entrainement.

Lancement manuel, sur son dataset personnel :
    DBT_DATASET=dbt_ouma python3 ml/donki/predire.py
"""

import os
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from google.cloud import bigquery

PROJET = "votre-projet-gcp"

DATASET_FEATURES = os.getenv("DBT_DATASET", "dbt_prod")
TABLE_FEATURES = "donki_features"

DATASET_ML = "ml"
TABLE_PREDICTIONS = "donki_predictions"

# Seuil choisi a l'entrainement (entrainement.ipynb, section 13) :
# rappel 0,71 et precision 0,55 sur le jeu de test. Le seuil n'est pas
# enregistre dans le modele, c'est ce script qui l'applique.
SEUIL = 0.4

# Coupure entre entrainement et test. Elle permet au tableau de bord de
# n'evaluer le modele que sur des eruptions qu'il n'a jamais vues.
COUPURE = pd.Timestamp("2025-01-01", tz="UTC")

DOSSIER_SCRIPT = os.path.dirname(os.path.abspath(__file__))
CHEMIN_MODELE = os.path.join(DOSSIER_SCRIPT, "modele_cme.pkl")


def trouver_racine(fichier):
    """Remonte les dossiers parents jusqu'a la racine du depot (pipeline.py)."""
    dossier = os.path.dirname(os.path.abspath(fichier))
    while dossier != os.path.dirname(dossier):
        if os.path.exists(os.path.join(dossier, "pipeline.py")):
            return dossier
        dossier = os.path.dirname(dossier)
    raise RuntimeError("Racine du depot introuvable (pipeline.py absent)")


load_dotenv(os.path.join(trouver_racine(__file__), ".env"))


def predire():
    """Charge le modele, predit sur la table de features, ecrit le resultat."""
    client = bigquery.Client(project=PROJET)

    # 1. Charger le modele. Il contient l'imputation, la mise a l'echelle,
    #    l'encodage ET la regression logistique : on ne reentraine rien ici.
    modele = joblib.load(CHEMIN_MODELE)

    # Les colonnes attendues sont lues DANS le modele, pas recopiees a la main :
    # si l'entrainement change de variables, la prediction suit.
    colonnes = list(modele.feature_names_in_)

    # 2. Lire la table de features produite par dbt.
    #    active_region_number ne sert pas au modele : il est lu uniquement
    #    pour etre affiche dans le tableau de bord.
    colonnes_sql = ",\n            ".join(colonnes)
    requete = f"""
        select
            solar_flare_id,
            flare_class,
            active_region_number,
            event_start_time,
            declenche_cme,
            {colonnes_sql}
        from `{PROJET}.{DATASET_FEATURES}.{TABLE_FEATURES}`
    """
    df = client.query(requete).to_dataframe(create_bqstorage_client=False)
    print(f"{len(df)} eruptions lues dans {DATASET_FEATURES}.{TABLE_FEATURES}.")

    if df.empty:
        print("Aucune ligne a predire : rien n'est ecrit.")
        return 0

    # Meme conversion qu'a l'entrainement : les entiers nullables de BigQuery
    # (<NA>) deviennent des flottants (NaN), que l'imputation sait traiter.
    numeriques = df[colonnes].select_dtypes(include="number").columns
    df[numeriques] = df[numeriques].astype(float)

    # 3. Predire.
    df["probabilite"] = modele.predict_proba(df[colonnes])[:, 1].round(4)
    df["prediction"] = df["probabilite"] >= SEUIL
    df["jeu"] = np.where(df["event_start_time"] < COUPURE, "entrainement", "test")
    df["date_prediction"] = datetime.now(timezone.utc)

    # 4. Traduire la prediction pour le tableau de bord, en langage client.

    # Niveau de risque : quatre paliers de probabilite. L'alerte commence
    # exactement au seuil, donc aux niveaux 3 et 4. right=False : la borne
    # basse est incluse (0,4 tombe dans "3 - Eleve", comme l'alerte).
    df["niveau_risque"] = pd.cut(
        df["probabilite"],
        bins=[0, 0.2, SEUIL, 0.7, 1.01],
        labels=["1 - Faible", "2 - Modéré", "3 - Élevé", "4 - Très élevé"],
        right=False,
    ).astype(str)

    df["alerte"] = np.where(df["prediction"], "Alerte CME", "Pas d'alerte")

    # Resultat : on compare l'alerte a ce qui s'est reellement passe.
    cme_reel = df["declenche_cme"].fillna(False).astype(bool)
    df["resultat"] = np.select(
        [
            df["prediction"] & cme_reel,
            ~df["prediction"] & cme_reel,
            df["prediction"] & ~cme_reel,
        ],
        ["CME anticipé", "CME manqué", "Fausse alerte"],
        default="Calme confirmé",
    )

    print(f"{int(df['prediction'].sum())} eruptions predites avec CME "
          f"({100 * df['prediction'].mean():.1f} %).")

    # Controle de coherence, sur le jeu de test uniquement : le rappel doit
    # retrouver 0,71 et la precision 0,55, mesures dans le notebook. Un ecart
    # signalerait un decalage entre entrainement et prediction.
    test = df[df["jeu"] == "test"]
    print("Resultats sur le jeu de test :")
    print(test["resultat"].value_counts().to_string())

    anticipes = (test["resultat"] == "CME anticipé").sum()
    manques = (test["resultat"] == "CME manqué").sum()
    fausses_alertes = (test["resultat"] == "Fausse alerte").sum()
    print(f"Rappel sur le jeu de test : {anticipes / (anticipes + manques):.2f} (attendu : 0,71)")
    print(f"Precision sur le jeu de test : {anticipes / (anticipes + fausses_alertes):.2f} (attendu : 0,55)")

    # 5. Ecrire dans BigQuery. WRITE_TRUNCATE : la table contient toujours
    #    la prediction courante pour chaque eruption.
    colonnes_sortie = [
        "solar_flare_id", "flare_class", "classe_lettre", "active_region_number",
        "event_start_time", "jeu", "prediction", "probabilite", "niveau_risque",
        "alerte", "resultat", "declenche_cme", "date_prediction",
    ]
    table_ref = f"{PROJET}.{DATASET_ML}.{TABLE_PREDICTIONS}"

    client.load_table_from_dataframe(
        df[colonnes_sortie],
        table_ref,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
    ).result()

    print(f"{len(df)} predictions ecrites dans {DATASET_ML}.{TABLE_PREDICTIONS}.")
    return len(df)


if __name__ == "__main__":
    predire()
