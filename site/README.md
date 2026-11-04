# Looptimum Site

This directory contains the static Astro site for `looptimum.io`.

## Content and intake

Shared copy and contact links live in `src/data/site.ts`. The current public
contact address is **contact@looptimum.io**. The pilot page uses email CTA links
and intake prompts; it does not contain a structured submission form or a form
handler. Update the shared data when changing contact guidance.

The site is built from the repository and published through the Git-based build
workflow. Source edits do not verify mail delivery, active provider settings or
live deployment health.

## Local static build

With Node.js/npm installed, use the locked dependencies from this directory:

```bash
npm ci
npm run build
```

The output is `dist/`. The checked-in Astro configuration selects static output.
`wrangler.jsonc` describes a Workers static-assets deployment, including its 404
handling; it is not an SSR Worker or a Pages Function application. Publishing
follows the repository's Git workflow. The presence of a local deploy script
does not establish what has been deployed or authorize a manual publication.

Domain aliases and redirects are infrastructure configuration, outside the
Astro page source. Check the actual provider setup before claiming that an
alias redirects correctly.

## Artwork and people

The homepage banner and social previews use
`public/brand/looptimum-landscape.png`. The banner spans the top of the homepage;
other pages display no banner. Social metadata uses the absolute
`https://looptimum.io` image URL.

Browser icons use `public/favicon-looptimum.png` and
`public/apple-touch-icon-looptimum.png`; the full-size icon is retained at
`public/brand/looptimum-icon.png`. The people section and portrait are part of
the current homepage. Preserve existing assets and direct references when
editing text.

## Evidence sources

Public proof points and charts come from the retained case-study packages:

- [Engineering mesh](../docs/examples/snappyhexmesh_campaign/README.md)
- [GPT training](../docs/examples/gpt_training_campaign/README.md)

The site mirrors selected public SVGs into `public/proof/` so the static build
can ship independently of the documentation tree. Keep each case study's
conditions and limitations with its claims; source/build success is not fresh
scientific validation.
