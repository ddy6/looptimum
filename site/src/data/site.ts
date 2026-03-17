export const navItems = [
  { href: "/", label: "Home" },
  { href: "/how-it-works/", label: "How It Works" },
  { href: "/use-cases/", label: "Use Cases" },
  { href: "/evidence/", label: "Evidence" },
  { href: "/pilot/", label: "Pilot" },
];

export const siteConfig = {
  siteUrl: "https://looptimum.io",
  contactEmail: "contact@looptimum.com",
  contactHref: "mailto:contact@looptimum.com?subject=Looptimum%20pilot%20fit%20review",
  ogImagePath: "/og-card.svg",
};

export const heroMetrics = [
  { value: "72.9%", label: "Fewer mesh cells", detail: "658,647 to 178,473" },
  { value: "91.0%", label: "Lower solver wall clock", detail: "1.806M s to 162,928 s" },
  { value: "11.1x", label: "Solver speedup", detail: "Validated coarse candidate" },
  { value: "<1%", label: "Outlet-flow drift", detail: "All major outlets" },
  { value: "<0.5", label: "MAP / PP drift (mmHg)", detail: "Aggregate pressure parity" },
];

export const workflowSteps = [
  {
    title: "Suggest",
    body:
      "Looptimum proposes the next bounded trial using the current observation set instead of broad sweep scheduling.",
  },
  {
    title: "Evaluate",
    body:
      "Your evaluator runs where it already lives: cluster jobs, scripts, CI runners, solver hosts, or lab workflows.",
  },
  {
    title: "Ingest",
    body:
      "Results are recorded into local files so the loop resumes cleanly after interruptions and leaves an auditable trail.",
  },
];

export const useCases = [
  {
    title: "Simulation and engineering",
    body:
      "Mesh controls, solver tolerances, calibration knobs, and workflow parameters where every run costs serious compute or analyst time.",
  },
  {
    title: "Infrastructure tuning",
    body:
      "Concurrency, retry policy, memory limits, thread counts, cache TTLs, and resource controls with measurable cost or latency impact.",
  },
  {
    title: "ML and evaluation loops",
    body:
      "Training recipe knobs, evaluation thresholds, batch sizes, and runtime controls when experiments are slow and failures are expensive.",
  },
  {
    title: "Operational process tuning",
    body:
      "Lab workflows, ETL processes, and production runbooks where throughput, quality, and cost need to be balanced under guardrails.",
  },
];

export const evidenceHighlights = [
  "216-point bounded search space",
  "21 trials executed",
  "8 random starts, 13 surrogate-guided trials",
  "Validated coarse-mesh candidate selected from campaign trial 15",
];

export const validationChecks = [
  "All major outlet flows within 1%",
  "Aggregate MAP within 0.5 mmHg",
  "Aggregate PP within 0.5 mmHg",
  "Solver reached 4.999946 s against a 5.0 s target",
];

export const intakeQuestions = [
  "What process or model are you optimizing?",
  "How expensive is one evaluation in time, compute, or operational cost?",
  "How many bounded knobs matter in the first pilot?",
  "What environment runs the evaluation today?",
  "What security, offline, or client-control constraints apply?",
];

export const repoLinks = {
  repo: "https://github.com/ddy6/looptimum",
  caseStudy:
    "https://github.com/ddy6/looptimum/tree/main/docs/examples/snappyhexmesh_campaign",
  pilot: "https://github.com/ddy6/looptimum/blob/main/PILOT.md",
  intake: "https://github.com/ddy6/looptimum/blob/main/intake.md",
};
