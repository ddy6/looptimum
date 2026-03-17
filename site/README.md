# Looptimum Site

This directory contains the first-pass static Astro site for `looptimum.io`.

## Local Development

Prerequisite: Node.js and npm must be installed locally. They are not available
in the current coding environment, so the site scaffold was created but not
built here.

From this directory:

```bash
npm install
npm run dev
```

Build for production:

```bash
npm run build
```

## Cloudflare Pages

Recommended Cloudflare Workers Builds settings:

- project root: `site`
- build command: `npm run build`
- deploy command: `npx wrangler deploy`
- production branch: `main`

This site is intentionally configured as a static Astro build deployed through
Workers Builds using Wrangler assets, not as an SSR Worker.

Primary production domain:

- `looptimum.io`

Current public contact address in the site:

- `contact@looptimum.com`

Alias domains that should redirect to the primary domain:

- `looptimum.com`
- `looptimum.dev`

For the alias domains, use Cloudflare Bulk Redirects or Single Redirects in the
Cloudflare dashboard after the domains are on the same account. Configure the
redirects so they forward to `https://looptimum.io` while preserving path
suffixes and query strings.

If `looptimum.com` and `looptimum.dev` are redirect-only alias domains, add
them to Cloudflare and create proxied placeholder DNS records so Cloudflare can
receive the request before applying the redirect. The standard placeholder IPv4
address is `192.0.2.1`.

Recommended redirect intent:

- `looptimum.com` -> `looptimum.io`
- `looptimum.dev` -> `looptimum.io`

Those domain redirects are not handled inside the Astro site itself.

## Content Sources

The proof points and charts in the site are derived from the sanitized public
case-study package in:

- `docs/examples/snappyhexmesh_campaign/`

The current site mirrors selected public-safe SVG charts into `public/proof/`
so the marketing site can ship independently of the docs tree.

## Next Implementation Step

The pilot page currently uses static CTA links and intake prompts. The next
step is to add a real Cloudflare Pages form handler or Pages Function so the
site can accept structured submissions without relying on email.
