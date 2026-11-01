{{ config(materialized='table') }}

-- Faits : une ligne par détection instrumentale NOAA SWPC.
-- Grain plus fin que DONKI : une même éruption peut générer
-- plusieurs détections (rayons X, radio, optique).

with observations as (
    select * from {{ ref('stg_noaa__events') }}
)

select
    event_id,

    -- Clés de dimension
    date(event_start_time) as date_key,
    active_region_number,
    event_type,

    -- Temps
    event_start_time,
    event_peak_time,
    event_end_time,

    -- Mesures
    timestamp_diff(event_end_time, event_start_time, minute) as duree_minutes,

    -- Contexte d'observation
    observatory,
    observation_quality,
    solar_region_location,
    radio_frequency

from observations