/** Validate the shared records at their import boundary, including Astro builds. */
const nonempty = (value) => typeof value === "string" && value.trim().length > 0;

function requireText(value, field) {
  if (!nonempty(value)) throw new Error(`${field} must be nonempty text`);
}

function requireObject(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${field} must be an object`);
  }
}

function requireList(value, field) {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error(`${field} must be a nonempty array`);
  }
}

/** Return a canonical local URL; asset paths may not contain queries/fragments. */
export function internalUrl(value, field, { asset = false } = {}) {
  requireText(value, field);
  if (!value.startsWith("/") || value.startsWith("//") || /[\\\s]/u.test(value)) {
    throw new Error(`${field} must be a canonical internal destination`);
  }
  const url = new URL(value, "https://looptimum.invalid");
  const path = value.split(/[?#]/u, 1)[0];
  if (url.pathname !== path || /%/u.test(path) || (asset && /[?#]/u.test(value))) {
    throw new Error(`${field} must be a canonical internal destination`);
  }
  if (asset && (path === "/" || path.endsWith("/"))) {
    throw new Error(`${field} must name a public asset file`);
  }
  return url;
}

export function validateCaseStudies(records) {
  requireList(records, "caseStudies");
  const slugs = new Set();
  for (const [index, record] of records.entries()) {
    const field = `caseStudies[${index}]`;
    requireObject(record, field);
    requireText(record.slug, `${field}.slug`);
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/u.test(record.slug)) {
      throw new Error(`${field}.slug must be a lowercase kebab-case route slug`);
    }
    if (/^larc(?:-|$)/u.test(record.slug)) {
      throw new Error(`${field}: LARC belongs on its separate page`);
    }
    if (slugs.has(record.slug)) throw new Error(`${field}.slug is duplicated`);
    slugs.add(record.slug);
    if (record.href !== `/evidence/${record.slug}/`) {
      throw new Error(`${field}.href must match its evidence slug`);
    }
    for (const key of ["title", "summary"]) requireText(record[key], `${field}.${key}`);
    requireList(record.metrics, `${field}.metrics`);
    for (const [i, metric] of record.metrics.entries()) {
      requireObject(metric, `${field}.metrics[${i}]`);
      for (const key of ["value", "label", "detail"]) {
        requireText(metric[key], `${field}.metrics[${i}].${key}`);
      }
    }
    requireList(record.proofAssets, `${field}.proofAssets`);
    const assets = new Set();
    for (const [i, proof] of record.proofAssets.entries()) {
      const prefix = `${field}.proofAssets[${i}]`;
      requireObject(proof, prefix);
      for (const key of ["title", "alt", "summary"]) requireText(proof[key], `${prefix}.${key}`);
      internalUrl(proof.src, `${prefix}.src`, { asset: true });
      if (assets.has(proof.src)) throw new Error(`${prefix}.src is duplicated`);
      assets.add(proof.src);
    }
    requireList(record.limitations, `${field}.limitations`);
    record.limitations.forEach((value, i) => requireText(value, `${field}.limitations[${i}]`));
    requireObject(record.cta, `${field}.cta`);
    requireText(record.cta.label, `${field}.cta.label`);
    internalUrl(record.cta.href, `${field}.cta.href`);
  }
}
