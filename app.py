"""SkyWatch — Météo spatiale : application de présentation du projet."""

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

RACINE = Path(__file__).parent
ORANGE, VIOLET, BLEU, ROUGE = "#F7922D", "#8B7CF6", "#59B4F7", "#E0531F"
TEXTE, GRIS, CARTE, BORD = "#EEF1F4", "#9AABBC", "rgba(15,33,49,0.85)", "#223A50"
COULEURS_NIVEAUX = {"1 - Faible": BLEU, "2 - Modéré": VIOLET, "3 - Élevé": ORANGE, "4 - Très élevé": ROUGE}
SEUIL = 0.4
LIEN_DASHBOARD = "https://datastudio.google.com/reporting/3ec43c75-d20f-4af2-bd2a-a20d25e7410d"
LIEN_GITHUB = "https://github.com/oumiims/skywatch-meteo-spatiale"

st.set_page_config(page_title="SkyWatch — Météo spatiale", page_icon="☀️", layout="wide")

# --------------------------------------------------------------------------
# Style
# --------------------------------------------------------------------------
st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@700;800&family=Roboto:wght@300;400;700&display=swap');
    html, body, [class*="css"], .stMarkdown, p, li {{ font-family: 'Roboto', sans-serif; }}
    .stApp {{
        background:
          radial-gradient(1px 1px at 12% 18%, #ffffff55 50%, transparent 51%),
          radial-gradient(1px 1px at 72% 8%, #ffffff44 50%, transparent 51%),
          radial-gradient(1.5px 1.5px at 38% 62%, #ffffff33 50%, transparent 51%),
          radial-gradient(1px 1px at 88% 44%, #ffffff55 50%, transparent 51%),
          radial-gradient(1px 1px at 22% 86%, #ffffff44 50%, transparent 51%),
          radial-gradient(1.5px 1.5px at 58% 30%, #ffffff33 50%, transparent 51%),
          radial-gradient(1200px 600px at 100% 0%, #3B1A0A 0%, transparent 60%),
          #070F18;
        background-size: 420px 420px, 380px 380px, 520px 520px, 460px 460px, 350px 350px, 600px 600px, 100% 100%, 100% 100%;
    }}
    [data-testid="stSidebar"] {{ background: #0B1621; border-right: 1px solid {BORD}; }}
    [data-testid="stHeader"] {{ background: transparent; }}
    h1, h2, h3 {{ font-family: 'Roboto', sans-serif; font-weight: 700; color: {TEXTE}; }}
    h2 {{ border-left: 6px solid {ORANGE}; padding-left: 14px; margin-top: 1.6rem; }}
    .logo {{ font-family: 'Orbitron', sans-serif; font-weight: 800; letter-spacing: 1px; }}
    .hero {{
        padding: 42px 44px; border-radius: 18px; margin-bottom: 26px;
        background: linear-gradient(100deg, rgba(7,15,24,0.95) 0%, rgba(11,22,33,0.9) 50%, rgba(138,58,14,0.85) 100%);
        border: 1px solid {BORD}; position: relative; overflow: hidden;
    }}
    .hero::after {{
        content: ""; position: absolute; right: -90px; top: -90px; width: 320px; height: 320px; border-radius: 50%;
        background: radial-gradient(circle at 35% 35%, #FFD27A 0%, {ORANGE} 45%, #C2410C 75%, transparent 76%);
        opacity: .9; filter: blur(1px);
    }}
    .hero h1 {{ font-size: 2.6rem; margin: 0 0 10px 0; max-width: 75%; }}
    .hero p {{ font-size: 1.15rem; color: #C9D6DE; max-width: 70%; margin: 0; }}
    .kpi {{
        background: {CARTE}; border: 1px solid {BORD}; border-radius: 14px; padding: 20px 22px; height: 100%;
    }}
    .kpi .valeur {{ font-size: 2.3rem; font-weight: 300; line-height: 1.1; }}
    .kpi .label {{ font-size: .95rem; color: {GRIS}; margin-top: 6px; }}
    .carte {{
        background: {CARTE}; border: 1px solid {BORD}; border-radius: 14px; padding: 22px 24px; height: 100%;
    }}
    .carte h4 {{ margin: 0 0 8px 0; font-size: 1.15rem; }}
    .carte p, .carte li {{ color: #C9D6DE; font-size: .98rem; }}
    .etape {{ font-size: .8rem; font-weight: 700; letter-spacing: 2px; text-transform: uppercase; }}
    .badge {{ display:inline-block; padding: 4px 12px; border-radius: 999px; font-size: .85rem; font-weight: 700;
              color: #0B1621; margin: 0 6px 6px 0; }}
    [data-testid="stMetric"] {{ background: {CARTE}; border: 1px solid {BORD}; border-radius: 14px; padding: 16px 20px; }}
    .stRadio > div {{ gap: .3rem; }}
    </style>
    """,
    unsafe_allow_html=True,
)


def hero(titre: str, sous_titre: str) -> None:
    st.markdown(f"<div class='hero'><h1>{titre}</h1><p>{sous_titre}</p></div>", unsafe_allow_html=True)


def kpis(elements: list[tuple[str, str, str]]) -> None:
    """elements = [(valeur, label, couleur)]"""
    for col, (valeur, label, couleur) in zip(st.columns(len(elements)), elements):
        col.markdown(
            f"<div class='kpi' style='border-top:4px solid {couleur}'>"
            f"<div class='valeur' style='color:{couleur}'>{valeur}</div><div class='label'>{label}</div></div>",
            unsafe_allow_html=True,
        )


def cartes(elements: list[tuple[str, str, str, str]]) -> None:
    """elements = [(sur-titre, titre, texte html, couleur)]"""
    for col, (sur, titre, texte, couleur) in zip(st.columns(len(elements)), elements):
        col.markdown(
            f"<div class='carte' style='border-left:5px solid {couleur}'>"
            f"<div class='etape' style='color:{couleur}'>{sur}</div><h4>{titre}</h4>{texte}</div>",
            unsafe_allow_html=True,
        )


def style_graphique(fig, hauteur: int = 380):
    fig.update_layout(
        height=hauteur, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(15,33,49,0.6)",
        margin=dict(l=20, r=20, t=30, b=20), font=dict(family="Roboto, Helvetica, Arial, sans-serif", size=14, color=TEXTE),
        xaxis=dict(gridcolor="#1B3045", zeroline=False), yaxis=dict(gridcolor="#1B3045", zeroline=False),
    )
    return fig


def espace(px_: int = 18) -> None:
    st.markdown(f"<div style='height:{px_}px'></div>", unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Données
# --------------------------------------------------------------------------
def en_booleen(serie: pd.Series) -> pd.Series:
    return serie.astype(str).str.lower().eq("true")


@st.cache_data
def charger_eruptions() -> pd.DataFrame:
    df = pd.read_csv(RACINE / "data" / "eruptions.csv")
    df["declenche_cme"] = en_booleen(df["declenche_cme"])
    return df


@st.cache_data
def charger_predictions() -> pd.DataFrame:
    df = pd.read_csv(RACINE / "data" / "predictions.csv")
    df["event_start_time"] = pd.to_datetime(df["event_start_time"].str.replace(" UTC", "", regex=False))
    df["declenche_cme"] = en_booleen(df["declenche_cme"])
    return df


@st.cache_resource
def charger_modele():
    return joblib.load(RACINE / "ml" / "donki" / "modele_cme.pkl")


eruptions = charger_eruptions()
predictions = charger_predictions()
test = predictions[predictions["jeu"] == "test"]

# --------------------------------------------------------------------------
# Navigation
# --------------------------------------------------------------------------
st.sidebar.markdown(
    f"<div class='logo' style='font-size:2rem'><span style='color:{TEXTE}'>SKY</span>"
    f"<span style='color:{ORANGE}'>WATCH</span></div>"
    f"<div style='color:{GRIS};margin-bottom:18px'>Météo spatiale · données NASA</div>",
    unsafe_allow_html=True,
)
page = st.sidebar.radio(
    "Navigation",
    ["☀️ Le projet", "🛠️ Le pipeline", "📈 L'analyse", "🤖 Le modèle", "🎛️ Simulateur"],
    label_visibility="collapsed",
)
st.sidebar.divider()
st.sidebar.link_button("📊 Dashboard Looker Studio", LIEN_DASHBOARD, width="stretch")
st.sidebar.link_button("💻 Code sur GitHub", LIEN_GITHUB, width="stretch")
st.sidebar.caption("Oumaïma Elazhari · Wild Code School 2026")

# --------------------------------------------------------------------------
# Page 1 : le projet
# --------------------------------------------------------------------------
if page == "☀️ Le projet":
    hero(
        "Peut-on anticiper les tempêtes solaires ?",
        "Dès la fin d'une éruption solaire, prévoir si elle sera suivie d'une éjection de masse coronale (CME), "
        "la seule menace qui laisse le temps d'agir.",
    )

    st.markdown("## Une éruption, trois menaces")
    cartes([
        ("8 minutes", "Rayons X", "<p>Radio et GPS perturbés. Déjà là quand on les détecte.</p>", BLEU),
        ("Quelques heures", "Particules", "<p>Satellites et astronautes exposés.</p>", VIOLET),
        ("1 à 3 jours", "CME", "<p>Tempête géomagnétique : <b>réseaux électriques menacés</b>.</p>", ORANGE),
    ])
    espace()
    st.markdown(
        f"<div class='carte' style='border-left:5px solid {ROUGE}'><h4>13 mars 1989, Québec</h4>"
        "<p>Une CME fait tomber le réseau électrique en 90 secondes : 6 millions de personnes restent "
        "9 heures sans électricité.</p></div>",
        unsafe_allow_html=True,
    )

    st.markdown("## Pour qui ?")
    c1, c2 = st.columns([1, 2])
    c1.markdown(
        f"<div class='carte' style='text-align:center'>"
        f"<div style='width:90px;height:90px;border-radius:50%;background:{ORANGE};color:#0B1621;"
        f"font-size:2rem;font-weight:700;display:flex;align-items:center;justify-content:center;margin:0 auto 12px'>RK</div>"
        f"<h4>Rachel Kim</h4><p>Coordinatrice de la gestion des urgences, Colorado</p></div>",
        unsafe_allow_html=True,
    )
    c2.markdown(
        "<div class='carte'><h4>Son besoin</h4><ul>"
        "<li>Plus de cinq portails consultés chaque matin, sans lien entre eux</li>"
        "<li>Un jargon difficile à expliquer à ses décideurs</li>"
        "<li>Voir la donnée derrière chaque score</li></ul>"
        "<p><b>SkyWatch traduit chaque éruption en un niveau de risque :</b></p>"
        + "".join(f"<span class='badge' style='background:{c}'>{n}</span>" for n, c in COULEURS_NIVEAUX.items())
        + "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("## Le projet en chiffres")
    n_mx = int(eruptions["classe_lettre"].isin(["M", "X"]).sum())
    kpis([
        (f"{len(eruptions):,}".replace(",", " "), "éruptions collectées depuis 2015", ORANGE),
        (f"{n_mx:,}".replace(",", " "), "éruptions M et X analysées", VIOLET),
        ("80", "tests de qualité dbt", BLEU),
        ("Lundi", "mise à jour automatique", "#3FB27F"),
    ])

    st.markdown("## Mon rôle")
    st.markdown(
        "<div class='carte'><p>Projet d'équipe <b>Wild Data Hub</b> (Wild Code School, août-octobre 2026) avec "
        "Alison Bourdet (astéroïdes) et Sofiane BenAbbou (catastrophes naturelles). "
        "<b>J'étais responsable du périmètre météo spatiale</b> : collecte, modèles dbt, analyse, "
        "Machine Learning et tableau de bord.</p></div>",
        unsafe_allow_html=True,
    )

# --------------------------------------------------------------------------
# Page 2 : le pipeline
# --------------------------------------------------------------------------
elif page == "🛠️ Le pipeline":
    hero("De l'API au tableau de bord", "Une chaîne de données automatisée, testée et reproductible.")

    etapes = [
        ("API", "NASA DONKI · NOAA", BLEU), ("Python", "collecte incrémentale", BLEU),
        ("BigQuery", "Bronze : brut", ORANGE), ("dbt staging", "Silver : nettoyé", "#C9D2DB"),
        ("dbt marts", "Gold : faits, features", "#F2C14E"), ("Modèle + Looker", "prédictions, dashboard", VIOLET),
    ]
    html = "<div style='display:flex;gap:10px;align-items:stretch;flex-wrap:wrap'>"
    for i, (titre, sous, couleur) in enumerate(etapes):
        html += (f"<div class='carte' style='flex:1;min-width:140px;border-top:4px solid {couleur};text-align:center'>"
                 f"<h4>{titre}</h4><p style='margin:0'>{sous}</p></div>")
        if i < len(etapes) - 1:
            html += f"<div style='align-self:center;color:{ORANGE};font-size:1.6rem'>➜</div>"
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)
    st.markdown(
        f"<div style='text-align:center;margin-top:12px;padding:12px;border:1px dashed {BLEU};border-radius:12px;color:{BLEU}'>"
        "<b>GitHub Actions</b> lance toute la chaîne chaque lundi à 6 h UTC</div>",
        unsafe_allow_html=True,
    )

    st.markdown("## Comment ?")
    cartes([
        ("01 · Collecter", "Collecte incrémentale",
         "<ul><li>Python et <code>requests</code>, clé lue dans un <code>.env</code></li>"
         "<li>Empreinte <code>row_hash</code> et <code>WRITE_APPEND</code> : on n'écrase jamais</li>"
         "<li>Historique depuis 2015 : un cycle solaire complet</li></ul>", BLEU),
        ("02 · Transformer", "Modélisation dbt",
         "<ul><li>Dédoublonnage par <code>row_number()</code></li>"
         "<li>Schéma en constellation : 2 faits, dimensions partagées</li>"
         "<li><b>80 tests</b> : unicité, non-nullité, intégrité</li></ul>", ORANGE),
        ("03 · Automatiser", "Orchestration",
         "<ul><li><code>pipeline.py</code> : collecte, <code>dbt build</code>, prédictions</li>"
         "<li>GitHub Actions chaque lundi</li>"
         "<li>Le dashboard lit directement la production</li></ul>", VIOLET),
    ])

    st.markdown("## Les difficultés rencontrées")
    cartes([
        ("Biais", "Catalogue incomplet", "<p>DONKI n'est exhaustif qu'à partir de M1.0 : analyse limitée à M et X.</p>", ROUGE),
        ("Jointure", "Deux numérotations", "<p>Règle trouvée : région DONKI = région NOAA + 10 000.</p>", ORANGE),
        ("Production", "Migration de l'API", "<p>Le 30 septembre, l'API NASA change d'adresse : corrigé le jour même.</p>", BLEU),
    ])

# --------------------------------------------------------------------------
# Page 3 : l'analyse
# --------------------------------------------------------------------------
elif page == "📈 L'analyse":
    hero("Ce que disent les données", "Le Soleil suit un cycle de 11 ans, et les éruptions les plus fortes déclenchent plus souvent une CME.")

    st.markdown("## Le cycle solaire")
    par_an = eruptions.groupby("annee").size().reset_index(name="eruptions")
    couleurs = [ORANGE if a == par_an.loc[par_an["eruptions"].idxmax(), "annee"] else "#8A5A2E" for a in par_an["annee"]]
    fig = go.Figure(go.Bar(x=par_an["annee"], y=par_an["eruptions"], marker_color=couleurs,
                           text=par_an["eruptions"], textposition="outside"))
    fig.update_layout(xaxis_title=None, yaxis_title="Éruptions cataloguées", xaxis=dict(dtick=1))
    st.plotly_chart(style_graphique(fig, 400), width="stretch")
    st.caption("Minimum solaire vers 2019, maximum en 2024.")

    c1, c2 = st.columns([1, 1])
    with c1:
        st.markdown("## Plus forte, plus risquée")
        mx = eruptions[eruptions["classe_lettre"].isin(["M", "X"])]
        taux = mx.groupby("classe_lettre")["declenche_cme"].mean().mul(100).round(1).reset_index()
        fig = px.bar(taux, x="classe_lettre", y="declenche_cme", text="declenche_cme",
                     color="classe_lettre", color_discrete_map={"M": ORANGE, "X": ROUGE})
        fig.update_traces(texttemplate="%{text} %", textposition="outside", width=0.5)
        fig.update_layout(showlegend=False, xaxis_title="Classe", yaxis_title="Part suivie d'une CME (%)", yaxis_range=[0, 100])
        st.plotly_chart(style_graphique(fig, 380), width="stretch")
        st.caption("Sous M1.0, le catalogue DONKI n'est pas exhaustif : seules M et X sont interprétables.")
    with c2:
        st.markdown("## Les régions les plus actives")
        regions = (eruptions.dropna(subset=["active_region_number"])
                   .groupby("active_region_number")["intensite"].sum().nlargest(10).reset_index())
        regions["region"] = regions["active_region_number"].astype(int).astype(str)
        fig = px.bar(regions.sort_values("intensite"), x="intensite", y="region", orientation="h",
                     color_discrete_sequence=[ORANGE])
        fig.update_layout(xaxis_title="Intensité cumulée", yaxis_title=None, yaxis_type="category")
        st.plotly_chart(style_graphique(fig, 380), width="stretch")

    st.markdown("## Les 10 éruptions les plus intenses")
    top = (eruptions.sort_values("intensite", ascending=False).head(10)
           [["flare_class", "date_key", "active_region_number", "declenche_cme", "nasa_link"]])
    st.dataframe(
        top, hide_index=True, width="stretch",
        column_config={
            "flare_class": "Classe", "date_key": "Date",
            "active_region_number": st.column_config.NumberColumn("Région", format="%d"),
            "declenche_cme": st.column_config.CheckboxColumn("Suivie d'une CME"),
            "nasa_link": st.column_config.LinkColumn("Fiche NASA", display_text="Voir"),
        },
    )

# --------------------------------------------------------------------------
# Page 4 : le modèle
# --------------------------------------------------------------------------
elif page == "🤖 Le modèle":
    hero("Le modèle de Machine Learning",
         "Classification binaire supervisée : régression logistique entraînée avant 2025, testée sur des éruptions jamais vues.")

    counts = test["resultat"].value_counts()
    anticipes, manques = int(counts.get("CME anticipé", 0)), int(counts.get("CME manqué", 0))
    fausses, calmes = int(counts.get("Fausse alerte", 0)), int(counts.get("Calme confirmé", 0))
    rappel = anticipes / max(anticipes + manques, 1)
    precision = anticipes / max(anticipes + fausses, 1)

    kpis([
        (f"{rappel:.0%}", "des CME détectées (rappel)", ORANGE),
        (f"{precision:.0%}", "des alertes confirmées (précision)", VIOLET),
        (str(len(test)), "éruptions de test (2025-2026)", BLEU),
        ("0,4", "seuil d'alerte", "#3FB27F"),
    ])

    st.markdown("## Comment il est construit")
    etapes = [("SimpleImputer", "médiane"), ("StandardScaler", "même échelle"),
              ("OneHotEncoder", "classe M / X"), ("LogisticRegression", "class_weight = balanced")]
    html = "<div style='display:flex;gap:10px;flex-wrap:wrap'>"
    for i, (t, s) in enumerate(etapes):
        couleur = ORANGE if i == len(etapes) - 1 else BLEU
        html += (f"<div class='carte' style='flex:1;min-width:150px;border-top:4px solid {couleur};text-align:center'>"
                 f"<h4><code>{t}</code></h4><p style='margin:0'>{s}</p></div>")
        if i < len(etapes) - 1:
            html += f"<div style='align-self:center;color:{ORANGE};font-size:1.6rem'>➜</div>"
    st.markdown(html + "</div>", unsafe_allow_html=True)
    st.caption("Comparée à un modèle naïf et à une forêt aléatoire. 8 variables connues à la fin de l'éruption, sans regard vers le futur.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("## Matrice de confusion")
        z = [[anticipes, fausses], [manques, calmes]]
        textes = [[f"{anticipes}<br>anticipées", f"{fausses}<br>fausses alertes"],
                  [f"{manques}<br>manquées", f"{calmes}<br>calmes confirmés"]]
        fig = go.Figure(go.Heatmap(z=z, x=["CME réelle", "Pas de CME"], y=["Alerte", "Pas d'alerte"],
                                   text=textes, texttemplate="%{text}", textfont=dict(size=18),
                                   colorscale=[[0, "#0F2131"], [1, ORANGE]], showscale=False))
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(style_graphique(fig, 360), width="stretch")
    with c2:
        st.markdown("## Peut-on faire confiance aux alertes ?")
        calib = test.groupby("niveau_risque")["declenche_cme"].mean().mul(100).round(0).reset_index()
        fig = px.bar(calib, x="niveau_risque", y="declenche_cme", text="declenche_cme",
                     color="niveau_risque", color_discrete_map=COULEURS_NIVEAUX)
        fig.update_traces(texttemplate="%{text:.0f} %", textposition="outside")
        fig.update_layout(showlegend=False, xaxis_title=None, yaxis_title="CME réelles (%)", yaxis_range=[0, 100])
        st.plotly_chart(style_graphique(fig, 360), width="stretch")

    st.caption("Seuil abaissé à 0,4 : pour un réseau électrique, manquer une CME coûte plus cher qu'une fausse alerte.")

    st.markdown("## Les dernières alertes émises")
    alertes = (predictions[predictions["alerte"] == "Alerte CME"]
               .sort_values("event_start_time", ascending=False).head(15))
    st.dataframe(
        alertes[["event_start_time", "flare_class", "active_region_number", "probabilite", "niveau_risque", "resultat"]],
        hide_index=True, width="stretch",
        column_config={
            "event_start_time": st.column_config.DatetimeColumn("Début", format="DD/MM/YYYY HH:mm"),
            "flare_class": "Classe",
            "active_region_number": st.column_config.NumberColumn("Région", format="%d"),
            "probabilite": st.column_config.ProgressColumn("Probabilité", min_value=0, max_value=1, format="%.2f"),
            "niveau_risque": "Niveau de risque", "resultat": "Ce qui s'est passé",
        },
    )

# --------------------------------------------------------------------------
# Page 5 : simulateur
# --------------------------------------------------------------------------
else:
    hero("Simulateur", "Décrivez une éruption : le modèle entraîné estime sa probabilité d'être suivie d'une CME.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<div class='etape' style='color:#F7922D'>L'éruption</div>", unsafe_allow_html=True)
        lettre = st.radio("Classe", ["M", "X"], horizontal=True)
        multiplicateur = st.slider("Multiplicateur (ex. M5.2 → 5,2)", 1.0, 9.9, 2.0, 0.1)
        duree = st.slider("Durée de l'éruption (minutes)", 5, 300, 30)
        montee = st.slider("Temps de montée jusqu'au pic (minutes)", 1, 120, 12)
    with c2:
        st.markdown("<div class='etape' style='color:#59B4F7'>Sa position et sa région</div>", unsafe_allow_html=True)
        latitude = st.slider("Latitude sur le Soleil (°, + = nord)", -40, 40, 15)
        longitude = st.slider("Longitude sur le Soleil (°, + = ouest)", -90, 90, 20)
        premiere = st.checkbox("Première éruption de cette région", value=False)
        nb_prec = 0 if premiere else st.slider("Éruptions précédentes de la même région", 0, 60, 5)
        heures = None if premiere else st.slider("Heures depuis l'éruption précédente", 0, 240, 24)

    intensite = (1000 if lettre == "M" else 10000) * multiplicateur
    entree = pd.DataFrame([{
        "log_intensite": np.log10(intensite),
        "duree_minutes": float(duree),
        "temps_montee_minutes": float(montee),
        "latitude": float(latitude),
        "longitude": float(longitude),
        "nb_eruptions_precedentes": float(nb_prec),
        "heures_depuis_precedente": np.nan if heures is None else float(heures),
        "classe_lettre": lettre,
    }])

    try:
        modele = charger_modele()
        entree = entree[list(modele.feature_names_in_)]
        proba = float(modele.predict_proba(entree)[0, 1])
    except Exception as erreur:  # le modèle doit être chargé avec la même version de scikit-learn
        st.error(f"Le modèle n'a pas pu être chargé : {erreur}")
        st.stop()

    bornes = [(0.2, "1 - Faible"), (SEUIL, "2 - Modéré"), (0.7, "3 - Élevé"), (1.01, "4 - Très élevé")]
    niveau = next(n for borne, n in bornes if proba < borne)
    couleur = COULEURS_NIVEAUX[niveau]

    espace(10)
    r1, r2 = st.columns([1, 1])
    with r1:
        jauge = go.Figure(go.Indicator(
            mode="gauge+number", value=proba * 100, number=dict(suffix=" %", font=dict(size=54, color=couleur)),
            gauge=dict(
                axis=dict(range=[0, 100], tickcolor=GRIS),
                bar=dict(color=couleur, thickness=0.3), bgcolor="rgba(0,0,0,0)", borderwidth=0,
                steps=[dict(range=[0, 20], color="#13314A"), dict(range=[20, 40], color="#2A2650"),
                       dict(range=[40, 70], color="#4A3218"), dict(range=[70, 100], color="#4A2014")],
                threshold=dict(line=dict(color=TEXTE, width=3), thickness=0.8, value=SEUIL * 100),
            ),
            title=dict(text=f"Probabilité de CME · éruption {lettre}{multiplicateur:.1f}", font=dict(size=16, color=GRIS)),
        ))
        st.plotly_chart(style_graphique(jauge, 300), width="stretch")
    with r2:
        alerte = "🚨 Alerte CME" if proba >= SEUIL else "Pas d’alerte"
        reel = test.groupby("niveau_risque")["declenche_cme"].mean().get(niveau)
        phrase = (f"Sur les éruptions de test classées « {niveau} », une CME a réellement suivi dans "
                  f"<b>{reel:.0%}</b> des cas." if reel is not None else "")
        st.markdown(
            f"<div class='carte' style='border:2px solid {couleur};text-align:center;padding:34px 24px'>"
            f"<div class='etape' style='color:{couleur}'>Niveau de risque</div>"
            f"<div style='font-size:2.4rem;font-weight:700;color:{couleur};margin:8px 0'>{niveau}</div>"
            f"<div style='font-size:1.4rem;margin-bottom:14px'>{alerte}</div>"
            f"<p>{phrase}</p></div>",
            unsafe_allow_html=True,
        )
