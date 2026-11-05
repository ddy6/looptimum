import { readFileSync, realpathSync, statSync } from "node:fs";
import { resolve, sep } from "node:path";
import { internalUrl, validateCaseStudies } from "../src/data/validate-case-studies.mjs";

function fileInside(root, relative, field) {
  const base = realpathSync(root);
  let path;
  try {
    path = realpathSync(resolve(base, relative));
  } catch {
    throw new Error(`${field}: missing file ${relative}`);
  }
  if (!path.startsWith(base + sep) || !statSync(path).isFile() || statSync(path).size === 0) {
    throw new Error(`${field}: expected a nonempty file inside ${base}`);
  }
  return path;
}

function decode(text) {
  return text.replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos|nbsp);/giu, (_, entity) => {
    if (entity.startsWith("#")) {
      return String.fromCodePoint(entity[1].toLowerCase() === "x"
        ? parseInt(entity.slice(2), 16) : parseInt(entity.slice(1), 10));
    }
    return { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " }[entity.toLowerCase()];
  });
}

const plainText = (text) => text.replace(/\s+/gu, " ").trim();
const textContent = (html) => plainText(decode(html.replace(/<[^>]*>/gu, " ")));

function attributes(tag) {
  const result = {};
  for (const match of tag.matchAll(/([^\s"'<>/=]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))/gu)) {
    result[match[1].toLowerCase()] = decode(match[2] ?? match[3] ?? match[4]);
  }
  return result;
}

function pagePath(url, root) {
  const relative = url.pathname.slice(1);
  if (!relative || relative.endsWith("/")) return `${relative}index.html`;
  try {
    if (statSync(resolve(root, relative)).isFile()) return relative;
  } catch {
    // A slashless route can still have a generated directory index.
  }
  return `${relative}/index.html`;
}

/** Check real generated destinations and figure context, using the same records. */
export function validateBuiltCaseStudies(records, { publicDir, outputDir }) {
  validateCaseStudies(records);
  const index = readFileSync(fileInside(outputDir, "evidence/index.html", "case-study index"), "utf8")
    .replace(/<!--[\s\S]*?-->/gu, "");
  for (const record of records) {
    const prefix = `case study ${record.slug}`;
    const html = readFileSync(fileInside(outputDir, pagePath(internalUrl(record.href, prefix), outputDir), prefix), "utf8")
      .replace(/<!--[\s\S]*?-->/gu, "");
    const indexText = textContent(index);
    for (const copy of [record.title, record.summary, record.limitations[0], ...record.metrics.flatMap((metric) => [metric.value, metric.label])]) {
      if (!indexText.includes(plainText(copy))) throw new Error(`${prefix}: missing index copy ${copy}`);
    }
    const detailText = textContent(html);
    for (const copy of [record.title, record.summary, ...record.limitations, ...record.metrics.flatMap((metric) => [metric.value, metric.label, metric.detail])]) {
      if (!detailText.includes(plainText(copy))) throw new Error(`${prefix}: missing detail copy ${copy}`);
    }
    const indexLinks = [...index.matchAll(/<a\b[^>]*>/giu)].map((m) => attributes(m[0]).href);
    if (!indexLinks.includes(record.href)) throw new Error(`${prefix}: missing index route link`);
    const figures = [...html.matchAll(/<figure\b[^>]*>([\s\S]*?)<\/figure>/giu)].map((m) => m[1]);
    for (const proof of record.proofAssets) {
      const relative = internalUrl(proof.src, `${prefix} proof`, { asset: true }).pathname.slice(1);
      const original = fileInside(publicDir, relative, `${prefix} public proof`);
      const built = fileInside(outputDir, relative, `${prefix} built proof`);
      if (!readFileSync(original).equals(readFileSync(built))) throw new Error(`${prefix}: built proof differs from public asset`);
      const figure = figures.find((value) => [...value.matchAll(/<img\b[^>]*>/giu)]
        .some((m) => attributes(m[0]).src === proof.src && attributes(m[0]).alt === proof.alt));
      const caption = figure?.match(/<figcaption\b[^>]*>([\s\S]*?)<\/figcaption>/iu)?.[1];
      if (!caption || !textContent(caption).includes(plainText(proof.title)) || !textContent(caption).includes(plainText(proof.summary))) {
        throw new Error(`${prefix}: proof must render with matching alt text and figure context: ${proof.src}`);
      }
    }
    const target = internalUrl(record.cta.href, `${prefix} CTA`);
    const destination = readFileSync(fileInside(outputDir, pagePath(target, outputDir), `${prefix} CTA`), "utf8")
      .replace(/<!--[\s\S]*?-->/gu, "");
    if (target.hash) {
      const id = decodeURIComponent(target.hash.slice(1));
      const ids = [...destination.matchAll(/<[a-z][^>]*>/giu)].map((m) => attributes(m[0]).id);
      if (!ids.includes(id)) throw new Error(`${prefix}: missing CTA fragment ${target.hash}`);
    }
    const links = [...html.matchAll(/<a\b([^>]*)>([\s\S]*?)<\/a>/giu)];
    if (!links.some((m) => attributes(m[1]).href === record.cta.href && textContent(m[2]) === record.cta.label)) {
      throw new Error(`${prefix}: missing rendered CTA`);
    }
  }
}
