`major_cities.csv` is the free Basic version of
[SimpleMaps' US Cities Database](https://simplemaps.com/data/us-cities) and
[SimpleMaps' Canada Cities Database](https://simplemaps.com/data/canada-cities)
(Pareto Software, LLC), merged and filtered to population >= 5,000
(7,253 rows), downloaded 2026-08-24. Replaces the old hand-curated
`MAJOR_CITIES` list in `renderer/adapters/radar.py` -- see `EDM-v3l`.

Both free databases are licensed under Creative Commons Attribution 4.0 and
require a link back to the source page from a public webpage where the data
is used, before use in production:

- https://simplemaps.com/data/us-cities
- https://simplemaps.com/data/canada-cities

**Compliance note, not yet fully satisfied**: neither this repo
(`jstevenscl/edm`) nor the standalone Classic4Kast Video+ repo
(`jstevenscl/classic4kast-video`) is a public webpage today -- both are
private GitHub repos. This file is the attribution of record for now
(same pattern as `renderer/music/pixabay/NOTICE.md`), but the license's
actual "public webpage" backlink requirement isn't met until either repo
goes public, or some other public page (e.g. a project website) links back
to the SimpleMaps pages above. Flag this again before any public/standalone
release.

Canada data additionally includes Statistics Canada content under the
Open Government Licence -- Canada.
