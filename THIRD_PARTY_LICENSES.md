# Third-Party Licenses

This repository vendors third-party assets used by the `renderer` service.
Each is credited below by origin and license.

## netbymatt/ws4kp

- **Repository:** https://github.com/netbymatt/ws4kp
- **License:** MIT
- **Used for:**
  - Fonts — `renderer/renderer/fonts/Star4000*.woff`
  - Icons — `renderer/renderer/icons_all/` (current-conditions, moon-phases,
    regional-maps)
  - PNG screen templates — `renderer/renderer/templates/*.png`

ws4kp itself credits the fonts and icons as fan recreations, not official
Weather Channel assets. Per its own attribution (reproduced in
`renderer/renderer/icons_all/NOTICE.md`):

> The icons were created by Charles Abel and Nick Smith
> (http://twcclassics.com/downloads/icons.html) as well as by Malek Masoud.
> The fonts were originally created by Nick Smith
> (http://twcclassics.com/downloads/fonts.html).

Licensed under MIT — see the upstream repository
(https://github.com/netbymatt/ws4kp) for the full license text. MIT permits
commercial use, modification, and redistribution; the notice above and this
file satisfy the license's copyright/attribution-preservation requirement
for these files.

## netbymatt/ws4kp-music

- **Repository:** https://github.com/netbymatt/ws4kp-music
- **License:** MIT-adjacent, per that repository's own README
- **Used for:** Default background music tracks —
  `renderer/renderer/music/default/*.mp3`

Per the upstream README (reproduced in
`renderer/renderer/music/default/NOTICE.md`), these 10 tracks are
AI-generated (Suno.ai), styled after 1990s Weather Channel music, and are
not recreations or rips of any specific copyrighted recording.

Licensed under MIT — see the upstream repository
(https://github.com/netbymatt/ws4kp-music) for the full license text.

## Pixabay

- **Source:** https://pixabay.com/
- **License:** [Pixabay Content License](https://pixabay.com/service/license-summary/)
  — free for commercial use, no attribution required
- **Used for:** Additional background music tracks —
  `renderer/renderer/music/pixabay/*.mp3`

9 individually-downloaded tracks selected 2026-08-24 for the same
lounge-jazz/"elevator music" mood as the `ws4kp-music` default set. Credited
by track and artist in `renderer/renderer/music/pixabay/NOTICE.md`, though
attribution isn't required by the license.

## Notes

- This repository does **not** ship the "extended" music set that exists in
  the upstream development tree. Those tracks have uncertain provenance and
  are excluded from this build.
- No other third-party creative assets (icons, fonts, images, or audio) are
  vendored into this repository beyond what is listed above.
