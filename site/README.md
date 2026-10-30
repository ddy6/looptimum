# Looptimum Site

This directory contains the static Astro site for `looptimum.io`.

## Local Development

Prerequisite: Node.js and npm must be installed locally.

From this directory:

```bash
npm install
npm run dev
```

For a local copy review at `http://127.0.0.1:4321/`:

```bash
npm run dev -- --host 127.0.0.1 --port 4321
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

The Home page banner and social previews (Open Graph and X) use
`public/brand/looptimum-landscape.png`. The banner spans the window at the very
top of the Home page, above the existing navigation and page headings. Its
height is capped on wide screens, with the image cropped without distortion.
Other pages display no banner.
Social metadata uses the absolute `https://looptimum.io` image URL on every page.

Browser icons use `public/favicon-looptimum.png` (64 × 64) and
`public/apple-touch-icon-looptimum.png` (180 × 180), derived from the supplied
Looptimum profile image with the white corners removed and the circle enlarged.
The full-size edited artwork is kept at `public/brand/looptimum-icon.png`.

The proof points and charts in the site are derived from the sanitized public
case-study packages in:

- `docs/examples/snappyhexmesh_campaign/`
- `docs/examples/gpt_training_campaign/`

The site mirrors selected public-safe SVG charts from those packages into
`public/proof/` so the static build can ship independently of the docs tree.

## Next Implementation Step

The pilot page currently uses static CTA links and intake prompts. The next
step is to add a real Cloudflare Pages form handler or Pages Function so the
site can accept structured submissions without relying on email.
