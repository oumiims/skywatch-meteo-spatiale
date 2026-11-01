{{ config(materialized='table') }}

-- Faits : une ligne par éruption solaire cataloguée par la NASA.
-- Grain : un événement FLR identifié par son flrID.

with eruptions as (
    select * from {{ ref('stg_donki__solar_flares') }}
)

select
    solar_flare_id,

    -- Clé de dimension
    date(event_start_time) as date_key,
    active_region_number,

    -- Temps
    event_start_time,
    event_peak_time,
    event_end_time,

    
    -- Mesures
    timestamp_diff(event_end_time, event_start_time, minute) as duree_minutes,
    flare_class,
    left(flare_class, 1)                                     as classe_lettre,
    cast(substr(flare_class, 2) as float64)                  as classe_multiplicateur,

    -- Cible du modèle : l'éruption est-elle associée à une éjection de masse
    -- coronale ? C'est le CME qui menace les réseaux, pas l'éruption elle-même.
    regexp_contains(ifnull(to_json_string(linked_events), ''), 'CME') as declenche_cme,

    -- Contexte
    solar_region_location,
    nasa_link

from eruptions