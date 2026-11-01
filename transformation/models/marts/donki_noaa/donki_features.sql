{{ config(materialized='table') }}

-- Table de caracteristiques pour le modele de prediction des CME.
-- Grain : une ligne par eruption solaire de classe M ou X.
--
-- Regle appliquee a chaque colonne : l'information doit etre disponible
-- a la fin de l'eruption. Tout ce qui n'est connu qu'apres est exclu.

with eruptions as (
    select *
    from {{ ref('fct_solar_flares') }}
    where classe_lettre in ('M', 'X')
)

select
    solar_flare_id,
    event_start_time,

    -- Intensite
    flare_class,
    classe_lettre,
    classe_multiplicateur,
    case classe_lettre when 'M' then 1000 when 'X' then 10000 end
        * classe_multiplicateur                             as intensite,
    log10(case classe_lettre when 'M' then 1000 when 'X' then 10000 end
        * classe_multiplicateur)                            as log_intensite,

    -- Profil temporel : connu a la fin de l'eruption
    case when duree_minutes between 0 and 600
         then duree_minutes end                             as duree_minutes,
    timestamp_diff(event_peak_time, event_start_time, minute) as temps_montee_minutes,

    -- Position sur le disque solaire. La longitude compte : par la rotation
    -- solaire, un CME issu de l'hemisphere ouest est dirige vers la Terre.
    -- Convention retenue : nord et ouest positifs.
    safe_cast(regexp_extract(solar_region_location, r'^[NS](\d+)') as int64)
        * if(starts_with(solar_region_location, 'N'), 1, -1) as latitude,
    safe_cast(regexp_extract(solar_region_location, r'[EW](\d+)$') as int64)
        * if(regexp_contains(solar_region_location, r'W\d+$'), 1, -1) as longitude,

    -- Historique de la region active, calcule SANS regarder le futur :
    -- la fenetre s'arrete a la ligne precedente. Un simple count(*) groupe
    -- par region inclurait des eruptions posterieures — fuite de donnees.
    count(*) over (
        partition by active_region_number
        order by event_start_time
        rows between unbounded preceding and 1 preceding
    )                                                       as nb_eruptions_precedentes,

    timestamp_diff(
        event_start_time,
        lag(event_start_time) over (
            partition by active_region_number
            order by event_start_time
        ),
        hour
    )                                                       as heures_depuis_precedente,

    active_region_number,

    -- Cible
    declenche_cme

from eruptions