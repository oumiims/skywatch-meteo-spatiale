{{ config(materialized='view') }}

select
    row_hash as event_id,

    -- Temps de l'événement
    begin_datetime as event_start_time,
    max_datetime   as event_peak_time,
    end_datetime   as event_end_time,

    -- Nature de l'événement
    type       as event_type,
    coded_type as event_type_code,

    -- Contexte d'observation
    observatory,
    nullif(trim(quality), '')  as observation_quality,

    -- NOAA utilise un format historique à 4 chiffres ; DONKI et la littérature actuelle utilisent le numéro complet. On aligne sur DONKI.
    nullif(region, 0) + 10000  as active_region_number,
    nullif(trim(location), '') as solar_region_location,
    nullif(trim(frequency), '') as radio_frequency,

    -- Métadonnées techniques
    inserted_at

from {{ source('raw_noaa', 'raw_noaa_events') }}