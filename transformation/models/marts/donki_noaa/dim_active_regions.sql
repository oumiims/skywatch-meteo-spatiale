{{ config(materialized='table') }}

-- Dimension conforme : une région active du Soleil.
-- Pivot entre les éruptions cataloguées par DONKI et les détections NOAA.

with regions_donki as (
    select
        active_region_number,
        count(*) as nb_eruptions_donki
    from {{ ref('stg_donki__solar_flares') }}
    where active_region_number is not null
    group by 1
),

regions_noaa as (
    select
        active_region_number,
        count(*) as nb_observations_noaa
    from {{ ref('stg_noaa__events') }}
    where active_region_number is not null
    group by 1
),

toutes_regions as (
    select active_region_number from regions_donki
    union distinct
    select active_region_number from regions_noaa
)

select
    r.active_region_number,
    coalesce(d.nb_eruptions_donki, 0)   as nb_eruptions_donki,
    coalesce(n.nb_observations_noaa, 0) as nb_observations_noaa

from toutes_regions r
left join regions_donki d on r.active_region_number = d.active_region_number
left join regions_noaa  n on r.active_region_number = n.active_region_number