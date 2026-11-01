{{ config(materialized='view') }}

-- Vue de restitution : une ligne par éruption, dimensions aplaties.
-- Looker Studio joint mal un schéma en étoile : les jointures sont faites ici,
-- une fois pour toutes, et l'outil ne lit qu'une seule table.

with eruptions as (
    select * from {{ ref('fct_solar_flares') }}
),

calendrier as (
    select date_key, annee, trimestre, mois, nom_mois, premier_jour_mois
    from {{ ref('dim_date') }}
),

regions as (
    select active_region_number, nb_eruptions_donki, nb_observations_noaa
    from {{ ref('dim_active_regions') }}
)

select
    e.solar_flare_id,

    -- Temps
    e.date_key,
    c.annee,
    c.trimestre,
    c.nom_mois,
    c.premier_jour_mois,
    e.event_start_time,

    -- Intensité
    e.flare_class,
    e.classe_lettre,
    e.classe_multiplicateur,
    case e.classe_lettre
        when 'A' then 1    when 'B' then 10    when 'C' then 100
        when 'M' then 1000 when 'X' then 10000
    end * e.classe_multiplicateur as intensite,

    -- Risque
    e.declenche_cme,
    -- Version numérique : la moyenne de cette colonne donne directement le taux
    -- d'association à un CME, exploitable comme métrique dans l'outil de restitution.
    cast(e.declenche_cme as int64) as cme_numerique,
    e.classe_lettre in ('M', 'X') as est_significative,

    -- Durée
    -- Durées aberrantes neutralisées : 4 négatives et 4 au-delà de 10 heures,
    -- 8 lignes sur 3 065 qui multipliaient l'écart-type par 700.
    case when e.duree_minutes between 0 and 600 then e.duree_minutes end as duree_minutes,

    -- Région active
    e.active_region_number,
    r.nb_eruptions_donki   as nb_eruptions_region,
    r.nb_observations_noaa as nb_detections_noaa_region,
    e.solar_region_location,

    e.nasa_link

from eruptions e
left join calendrier c on e.date_key = c.date_key
left join regions    r on e.active_region_number = r.active_region_number