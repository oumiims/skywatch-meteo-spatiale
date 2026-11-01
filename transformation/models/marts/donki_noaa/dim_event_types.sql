{{ config(materialized='table') }}

-- Référentiel des types d'événements NOAA : décode les codes à trois lettres
-- (XRA, RBR, RSP...) en libellés lisibles pour la BI.

with types_observes as (
    select
        event_type,
        count(*) as nb_evenements
    from {{ ref('stg_noaa__events') }}
    group by 1
),

referentiel as (
    select * from {{ ref('noaa_event_types') }}
)

select
    t.event_type,
    r.libelle,
    r.famille,
    r.description,
    t.nb_evenements

from types_observes t
left join referentiel r on t.event_type = r.event_type