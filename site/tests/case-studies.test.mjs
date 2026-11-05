import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";
import { caseStudies } from "../src/data/site.ts";
import { internalUrl, validateCaseStudies } from "../src/data/validate-case-studies.mjs";
import { validateBuiltCaseStudies } from "../scripts/validate-built-site.mjs";

const sample = () => structuredClone({
  slug: "sample", href: "/evidence/sample/", title: "Sample & results", summary: "A bounded experiment.",
  metrics: [{ value: "<1%", label: "Drift", detail: "Against a fixed reference" }],
  proofAssets: [{ title: "Loss & cost", src: "/proof/chart.svg", alt: 'A chart with "loss" & cost', summary: "Observed loss only." }],
  limitations: ["One experiment."], cta: { href: "/pilot/#contact", label: "Discuss a pilot" },
});

test("the actual typed case-study source satisfies the shared contract", () => {
  validateCaseStudies(caseStudies);
  assert.ok(caseStudies.length > 0);
});

const invalids = [
  ["missing slug", (r) => { delete r.slug; }, /slug/u],
  ["blank slug", (r) => { r.slug = " "; }, /slug/u],
  ["unsafe slug", (r) => { r.slug = "../escape"; }, /slug/u],
  ["mismatched route", (r) => { r.href = "/evidence/another/"; }, /href/u],
  ["LARC entry", (r) => { r.slug = "larc"; r.href = "/evidence/larc/"; }, /LARC/u],
  ["blank title", (r) => { r.title = " "; }, /title/u],
  ["missing summary", (r) => { delete r.summary; }, /summary/u],
  ["empty metrics", (r) => { r.metrics = []; }, /metrics/u],
  ["malformed metric", (r) => { r.metrics = [null]; }, /metrics/u],
  ...["value", "label", "detail"].map((key) => [`missing metric ${key}`, (r) => { delete r.metrics[0][key]; }, /metrics/u]),
  ["empty proofs", (r) => { r.proofAssets = []; }, /proofAssets/u],
  ["malformed proof", (r) => { r.proofAssets = [null]; }, /proofAssets/u],
  ...["title", "alt", "summary"].map((key) => [`blank proof ${key}`, (r) => { r.proofAssets[0][key] = " "; }, /proofAssets/u]),
  ["external proof", (r) => { r.proofAssets[0].src = "https://elsewhere.invalid/chart.svg"; }, /internal/u],
  ["traversing proof", (r) => { r.proofAssets[0].src = "/proof/../outside.svg"; }, /internal/u],
  ["encoded proof", (r) => { r.proofAssets[0].src = "/proof/%2e%2e/outside.svg"; }, /internal/u],
  ["duplicate proof", (r) => { r.proofAssets.push({ ...r.proofAssets[0] }); }, /duplicated/u],
  ["missing limitations", (r) => { delete r.limitations; }, /limitations/u],
  ["blank limitation", (r) => { r.limitations = [" "]; }, /limitations/u],
  ["malformed CTA", (r) => { r.cta = null; }, /cta/u],
  ["external CTA", (r) => { r.cta.href = "https://elsewhere.invalid/"; }, /internal/u],
  ["blank CTA label", (r) => { r.cta.label = " "; }, /label/u],
];
for (const [name, mutate, error] of invalids) {
  test(`rejects ${name}`, () => {
    const record = sample();
    mutate(record);
    assert.throws(() => validateCaseStudies([record]), error);
  });
}
test("rejects an empty or malformed manifest and duplicate slugs", () => {
  for (const records of [undefined, null, {}, [], [null], [sample(), sample()]]) {
    assert.throws(() => validateCaseStudies(records));
  }
});
test("internal URLs reject ambiguous hosts, traversal, query assets and empty filenames", () => {
  for (const value of ["//evil.invalid/a", "/a/../b", "/a\\b", "/a b", "/%2fescape"]) {
    assert.throws(() => internalUrl(value, "destination"));
  }
  for (const value of ["/proof/a.svg?raw", "/proof/a.svg#chart", "/proof/", "/"]) {
    assert.throws(() => internalUrl(value, "proof", { asset: true }));
  }
  assert.equal(internalUrl("/pilot/?campaign=sample#contact", "CTA").hash, "#contact");
});

const escape = (text) => text.replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), "looptimum-site-test-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const record = sample();
  const publicDir = join(root, "public");
  const outputDir = join(root, "dist");
  const put = (relative, body) => {
    const path = join(root, relative);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, body);
  };
  put("public/proof/chart.svg", "<svg>chart</svg>");
  put("dist/proof/chart.svg", "<svg>chart</svg>");
  const proof = record.proofAssets[0];
  put("dist/evidence/sample/index.html", `<h1>${escape(record.title)}</h1><p>${record.summary}</p><strong>${escape(record.metrics[0].value)}</strong> ${record.metrics[0].label}<p>${record.metrics[0].detail}</p><p>${record.limitations[0]}</p><figure><img src="${proof.src}" alt="${escape(proof.alt)}"><figcaption><h3>${escape(proof.title)}</h3><p>${proof.summary}</p></figcaption></figure><a href="${record.cta.href}">${record.cta.label}</a>`);
  put("dist/evidence/index.html", `<article><h3>${escape(record.title)}</h3><p>${record.summary}</p><strong>${escape(record.metrics[0].value)}</strong> ${record.metrics[0].label}<p>${record.limitations[0]}</p><a href="${record.href}">Read the case study</a></article>`);
  put("dist/pilot/index.html", '<main id="contact">Contact</main>');
  return { root, record, publicDir, outputDir, put, validate: () => validateBuiltCaseStudies([record], { publicDir, outputDir }) };
}
test("built records resolve assets, routes, escaped figure text and CTA fragments", (t) => fixture(t).validate());

test("a slashless CTA resolves an Astro directory route", (t) => {
  const f = fixture(t);
  f.record.cta.href = "/pilot";
  const path = "dist/evidence/sample/index.html";
  f.put(path, readFileSync(join(f.root, path), "utf8").replace('/pilot/#contact', '/pilot'));
  f.validate();
});
test("a commented-out index link is not a rendered route", (t) => {
  const f = fixture(t);
  const path = "dist/evidence/index.html";
  f.put(path, readFileSync(join(f.root, path), "utf8").replace('<a href="/evidence/sample/">Read the case study</a>', '<!-- <a href="/evidence/sample/">Read the case study</a> -->'));
  assert.throws(f.validate, /index route/u);
});
for (const [href, destination] of [["/guide.v1#contact", "dist/guide.v1/index.html"], ["/manual.html#contact", "dist/manual.html"]]) {
  test(`a CTA resolves the actual generated destination for ${href}`, (t) => {
    const f = fixture(t);
    f.record.cta.href = href;
    f.put(destination, '<main id="contact">Contact</main>');
    const path = "dist/evidence/sample/index.html";
    f.put(path, readFileSync(join(f.root, path), "utf8").replace('/pilot/#contact', href));
    f.validate();
  });
}

for (const missing of ["public/proof/chart.svg", "dist/proof/chart.svg", "dist/evidence/sample/index.html", "dist/evidence/index.html", "dist/pilot/index.html"]) {
  test(`build rejects missing ${missing}`, (t) => {
    const f = fixture(t);
    rmSync(join(f.root, missing));
    assert.throws(f.validate, /missing/u);
  });
}
for (const [name, path, before, after, error] of [
  ["missing alt", "dist/evidence/sample/index.html", 'alt="A chart with &quot;loss&quot; &amp; cost"', 'alt=""', /figure context/u],
  ["wrong image", "dist/evidence/sample/index.html", 'src="/proof/chart.svg"', 'src="/proof/other.svg"', /figure context/u],
  ["missing figure title", "dist/evidence/sample/index.html", "Loss &amp; cost", "Other chart", /figure context/u],
  ["missing figure summary", "dist/evidence/sample/index.html", "Observed loss only.", "", /figure context/u],
  ["missing caption", "dist/evidence/sample/index.html", "figcaption", "div", /figure context/u],
  ["missing CTA", "dist/evidence/sample/index.html", "Discuss a pilot", "Something else", /rendered CTA/u],
  ["missing CTA fragment", "dist/pilot/index.html", 'id="contact"', 'id="other"', /fragment/u],
  ["missing summary", "dist/evidence/index.html", "A bounded experiment.", "", /index copy/u],
  ["missing detail summary", "dist/evidence/sample/index.html", "A bounded experiment.", "", /detail copy/u],
  ["missing detail metric", "dist/evidence/sample/index.html", "Against a fixed reference", "", /detail copy/u],
  ["missing detail limitation", "dist/evidence/sample/index.html", "One experiment.", "", /detail copy/u],
  ["missing limitation", "dist/evidence/index.html", "One experiment.", "", /index copy/u],
  ["missing index destination", "dist/evidence/index.html", 'href="/evidence/sample/"', 'href="/evidence/other/"', /index route/u],
]) {
  test(`build rejects ${name}`, (t) => {
    const f = fixture(t);
    const content = readFileSync(join(f.root, path), "utf8");
    assert.ok(content.includes(before));
    f.put(path, content.replaceAll(before, after));
    assert.throws(f.validate, error);
  });
}
test("build rejects empty, changed and escaping proof assets", (t) => {
  const f = fixture(t);
  f.put("public/proof/chart.svg", "");
  assert.throws(f.validate, /nonempty/u);
  f.put("public/proof/chart.svg", "different");
  assert.throws(f.validate, /differs/u);
  rmSync(join(f.root, "public/proof/chart.svg"));
  f.put("outside.svg", "outside");
  symlinkSync(join(f.root, "outside.svg"), join(f.root, "public/proof/chart.svg"));
  assert.throws(f.validate, /inside/u);
});
