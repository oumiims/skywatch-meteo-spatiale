{{ config(materialized='view') }}

-- La couche brute conserve toutes les versions d'une éruption : NASA révise
-- ses événements a posteriori, soit en incrémentant versionId, soit en
-- enrichissant un champ (le lien vers le CME, par exemple). Le staging
-- n'expose que l'état courant : une ligne par éruption, la plus récente.

with derniere_version as (
    select
        *,
        row_number() over (
            partition by flrid
            order by versionid desc, inserted_at desc
        ) as rang
    from {{ source('raw_donki', 'solar_flares') }}
)

select
    flrid as solar_flare_id,

    -- Temps de l'éruption
    begintime as event_start_time,
    peaktime  as event_peak_time,
    endtime   as event_end_time,

    -- Intensité et localisation
    classtype                          as flare_class,
    nullif(trim(sourcelocation), '')   as solar_region_location,
    activeregionnum                    as active_region_number,

    -- Événements liés (CME, SEP) déclenchés par l'éruption
    linkedevents as linked_events,

    -- Traçabilité NASA
    catalog,
    versionid      as version_id,
    submissiontime as submission_time,
    replace(link, 'https://webtools.ccmc.gsfc.nasa.gov/DONKI/view/', 'https://ccmc.gsfc.nasa.gov/DONKI-Editor/view/') as nasa_link,    nullif(trim(note), '') as note,

    -- Métadonnées techniques
    inserted_at

from derniere_version
where rang = 1