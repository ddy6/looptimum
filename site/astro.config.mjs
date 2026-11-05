import { defineConfig } from "astro/config";
import { fileURLToPath } from "node:url";
import { caseStudies } from "./src/data/site.ts";
import { validateBuiltCaseStudies } from "./scripts/validate-built-site.mjs";

export default defineConfig({
  site: "https://looptimum.io",
  output: "static",
  integrations: [{
    name: "case-study-validation",
    hooks: {
      "astro:build:done": ({ dir }) => validateBuiltCaseStudies(caseStudies, {
        publicDir: fileURLToPath(new URL("./public/", import.meta.url)),
        outputDir: fileURLToPath(dir),
      }),
    },
  }],
});
