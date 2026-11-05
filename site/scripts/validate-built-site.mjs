import { readFileSync, realpathSync, statSync } from "node:fs";
import { resolve, sep } from "node:path";
import { parse } from "parse5";
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

const plainText = (text) => text.replace(/\s+/gu, " ").trim();
const excludedTags = new Set(["head", "script", "style", "template", "noscript"]);
const excluded = (node) => excludedTags.has(node.tagName);
const attribute = (node, name) => node.attrs?.find((attr) => attr.name === name)?.value;

function* elements(node, tagName) {
  if (excluded(node)) return;
  if (node.tagName && (!tagName || node.tagName === tagName)) yield node;
  for (const child of node.childNodes ?? []) yield* elements(child, tagName);
}

function rawText(node) {
  if (excluded(node) || node.nodeName === "#comment") return "";
  if (node.nodeName === "#text") return node.value;
  return (node.childNodes ?? []).map(rawText).join("");
}

const textContent = (node) => plainText(rawText(node));

function readPage(root, relative, field) {
  return parse(readFileSync(fileInside(root, relative, field), "utf8"));
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
  const index = readPage(outputDir, "evidence/index.html", "case-study index");
  const indexText = textContent(index);
  const indexLinks = [...elements(index, "a")].map((node) => attribute(node, "href"));
  for (const record of records) {
    const prefix = `case study ${record.slug}`;
    const html = readPage(outputDir, pagePath(internalUrl(record.href, prefix), outputDir), prefix);
    for (const copy of [record.title, record.summary, record.limitations[0], ...record.metrics.flatMap((metric) => [metric.value, metric.label])]) {
      if (!indexText.includes(plainText(copy))) throw new Error(`${prefix}: missing index copy ${copy}`);
    }
    const detailText = textContent(html);
    for (const copy of [record.title, record.summary, ...record.limitations, ...record.metrics.flatMap((metric) => [metric.value, metric.label, metric.detail])]) {
      if (!detailText.includes(plainText(copy))) throw new Error(`${prefix}: missing detail copy ${copy}`);
    }
    if (!indexLinks.includes(record.href)) throw new Error(`${prefix}: missing index route link`);
    const figures = [...elements(html, "figure")];
    for (const proof of record.proofAssets) {
      const relative = internalUrl(proof.src, `${prefix} proof`, { asset: true }).pathname.slice(1);
      const original = fileInside(publicDir, relative, `${prefix} public proof`);
      const built = fileInside(outputDir, relative, `${prefix} built proof`);
      if (!readFileSync(original).equals(readFileSync(built))) throw new Error(`${prefix}: built proof differs from public asset`);
      const figure = figures.find((node) => [...elements(node, "img")]
        .some((image) => attribute(image, "src") === proof.src && attribute(image, "alt") === proof.alt));
      const caption = figure && [...elements(figure, "figcaption")][0];
      if (!caption || !textContent(caption).includes(plainText(proof.title)) || !textContent(caption).includes(plainText(proof.summary))) {
        throw new Error(`${prefix}: proof must render with matching alt text and figure context: ${proof.src}`);
      }
    }
    const target = internalUrl(record.cta.href, `${prefix} CTA`);
    const destination = readPage(outputDir, pagePath(target, outputDir), `${prefix} CTA`);
    if (target.hash) {
      const id = decodeURIComponent(target.hash.slice(1));
      const ids = [...elements(destination)].map((node) => attribute(node, "id"));
      if (!ids.includes(id)) throw new Error(`${prefix}: missing CTA fragment ${target.hash}`);
    }
    const links = [...elements(html, "a")];
    if (!links.some((node) => attribute(node, "href") === record.cta.href && textContent(node) === record.cta.label)) {
      throw new Error(`${prefix}: missing rendered CTA`);
    }
  }
}
