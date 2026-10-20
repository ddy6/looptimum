export const navItems = [
  { href: "/", label: "Home" },
  { href: "/how-it-works/", label: "How it works" },
  { href: "/use-cases/", label: "Use cases" },
  { href: "/evidence/", label: "Evidence" },
  { href: "/larc/", label: "LARC" },
  { href: "/pilot/", label: "Pilot" },
  { href: "/#people", label: "People" },
];

export const siteConfig = {
  siteUrl: "https://looptimum.io",
  contactEmail: "contact@looptimum.io",
  contactHref: "mailto:contact@looptimum.io?subject=Looptimum%20pilot%20fit%20review",
  larcContactHref: "mailto:contact@looptimum.io?subject=Discuss%20a%20LARC%20project",
  ogImagePath: "/og-card.svg",
};

export const larcProjectArchetypes = [
  {
    title: "Integrated technical systems",
    body:
      "Software, hardware, models, and human workflows whose performance depends on how the parts work together.",
  },
  {
    title: "Computing limits",
    body:
      "Systems where simulation, training, inference, or coordination costs could make the proposed design impractical.",
  },
  {
    title: "Costly experiments",
    body:
      "Laboratory or physical systems where measurements are slow, expensive, or hard to repeat.",
  },
  {
    title: "Planning the first build",
    body:
      "Promising ideas that need a clearer account of the bottlenecks, tests, and milestones before implementation.",
  },
];

export const larcMethodSteps = [
  {
    title: "Scope",
    body: "Define the system, its constraints, and the technical questions that remain open.",
  },
  {
    title: "Identify bottlenecks",
    body: "Find the costs, resource limits, and design choices most likely to determine feasibility.",
  },
  {
    title: "Choose what to optimize",
    body: "Decide which variables matter and whether to tackle the problem in stages or smaller parts.",
  },
  {
    title: "Plan the tests",
    body: "Order the models, benchmarks, and experiments around what needs to be learned first.",
  },
  {
    title: "Support implementation",
    body: "Use the results to set validation criteria and decide what to build next.",
  },
];

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
      "Looptimum selects the next candidate from your parameter bounds, using the results collected so far.",
  },
  {
    title: "Evaluate",
    body:
      "Your script, cluster, solver, or lab workflow runs the trial in its existing environment.",
  },
  {
    title: "Ingest",
    body:
      "Record the score or failure in local files, then repeat. The saved history lets you review decisions and resume interrupted work.",
  },
];

interface UseCase {
  title: string;
  body: string;
  href?: string;
  linkLabel?: string;
}

export const useCases: UseCase[] = [
  {
    title: "Simulation and engineering",
    body:
      "Tune mesh controls, solver tolerances, or calibration parameters when each run takes substantial compute or analyst time.",
  },
  {
    title: "Infrastructure tuning",
    body:
      "Adjust concurrency, retries, memory limits, thread counts, or cache lifetimes against measured cost and latency.",
  },
  {
    title: "ML and evaluation loops",
    body:
      "Search training settings, batch sizes, or evaluation thresholds when experiments are slow and failed runs are costly.",
    href: "/evidence/gpt-training/",
    linkLabel: "Read the GPT training case study",
  },
  {
    title: "Operational process tuning",
    body:
      "Improve throughput, quality, or cost in lab workflows, ETL pipelines, and production processes while respecting operating limits.",
  },
];

export interface CaseStudyMetric {
  value: string;
  label: string;
  detail: string;
}

export interface CaseStudyProofAsset {
  title: string;
  src: string;
  alt: string;
  summary: string;
}

export interface CaseStudy {
  slug: string;
  href: string;
  title: string;
  summary: string;
  metrics: CaseStudyMetric[];
  proofAssets: CaseStudyProofAsset[];
  limitations: string[];
  cta: { href: string; label: string };
}

export const caseStudies: CaseStudy[] = [
  {
    slug: "engineering-mesh",
    href: "/evidence/engineering-mesh/",
    title: "A smaller simulation mesh",
    summary:
      "A 21-trial search found a smaller mesh, then a separate solver pass checked flow and pressure against the fine reference.",
    metrics: [
      { value: "72.9%", label: "Fewer cells", detail: "Selected coarse candidate" },
      { value: "91.0%", label: "Lower wall clock", detail: "Validated solver pass" },
      { value: "11.1x", label: "Speedup", detail: "Against the fine reference" },
    ],
    proofAssets: [
      {
        title: "Solver wall-clock comparison",
        src: "/proof/fine_vs_coarse_solver_runtime.svg",
        alt: "Bar chart comparing solver wall clock for the fine reference and validated coarse mesh",
        summary: "The selected coarse case reduced solver wall clock by 91.0%.",
      },
      {
        title: "Mesh cell-count comparison",
        src: "/proof/fine_vs_coarse_cell_count.svg",
        alt: "Bar chart comparing the cell counts of the fine reference and selected coarse mesh",
        summary:
          "The selected coarse mesh contained 72.9% fewer cells than the fine reference.",
      },
      {
        title: "Objective progression",
        src: "/proof/campaign_objective_progression.svg",
        alt: "Line and point chart showing objective loss across the engineering campaign",
        summary:
          "The campaign explored fewer than 10% of the bounded search space and identified a repeatable low-loss basin.",
      },
      {
        title: "Outlet-flow validation",
        src: "/proof/outlet_flow_relative_drift.svg",
        alt: "Chart showing outlet-flow drift for the selected coarse mesh against the fine reference",
        summary:
          "All major outlet flows remained within the stated 1% validation threshold.",
      },
      {
        title: "Aggregate pressure validation",
        src: "/proof/aggregate_pressure_drift.svg",
        alt: "Chart showing aggregate pressure drift for the selected coarse mesh against the fine reference",
        summary:
          "Aggregate MAP and pulse-pressure drift remained within the 0.5 mmHg acceptance band.",
      },
    ],
    limitations: ["Acceptance required a separate solver pass and mesh-independence checks."],
    cta: { href: "/pilot/", label: "Discuss a pilot" },
  },
  {
    slug: "gpt-training",
    href: "/evidence/gpt-training/",
    title: "A GPT training-recipe search",
    summary:
      "Ten evaluations tested four training controls. The selected model had lower held-out loss and fewer parameters than the fixed baseline.",
    metrics: [
      { value: "10/10", label: "Successful evaluations", detail: "4 initialization + 6 guided" },
      { value: "1.02%", label: "Lower held-out loss", detail: "Selected versus fixed baseline" },
      { value: "~25%", label: "Fewer parameters", detail: "Selected versus fixed baseline" },
    ],
    proofAssets: [
      {
        title: "Normalized objective progression",
        src: "/proof/gpt_campaign_objective_progression.svg",
        alt: "Normalized held-out loss across ten evaluations in an anonymized GPT training campaign",
        summary:
          "The guided phase produced the two strongest observed candidates; lower indexed loss is better.",
      },
      {
        title: "Baseline versus selected candidate",
        src: "/proof/gpt_baseline_vs_selected.svg",
        alt: "Zero-based indexed comparisons of held-out loss and parameter count for a fixed baseline and selected candidate",
        summary:
          "The selected candidate combined a modest loss improvement with a separate reduction in model parameters.",
      },
    ],
    limitations: [
      "Anonymized campaign with one seed and a small evaluation budget.",
      "The observed result does not establish statistical significance or global optimality.",
    ],
    cta: { href: "/pilot/", label: "Discuss a pilot" },
  },
];

export const validationChecks = [
  "All major outlet flows within 1%",
  "Aggregate MAP within 0.5 mmHg",
  "Aggregate PP within 0.5 mmHg",
  "Solver reached 4.999946 s against a 5.0 s target",
];

export const intakeQuestions = [
  "What are you optimizing, and how will you measure improvement?",
  "What does one evaluation cost in time, compute, or money?",
  "Which parameters can you change, and what are their limits?",
  "Where and how do you run evaluations today?",
  "What security, offline, or access requirements apply?",
];

export const repoLinks = {
  repo: "https://github.com/ddy6/looptimum",
  maintainer: "https://github.com/ddy6",
  caseStudy:
    "https://github.com/ddy6/looptimum/tree/main/docs/examples/snappyhexmesh_campaign",
  gptCaseStudy:
    "https://github.com/ddy6/looptimum/tree/main/docs/examples/gpt_training_campaign",
  pilot: "https://github.com/ddy6/looptimum/blob/main/PILOT.md",
  intake: "https://github.com/ddy6/looptimum/blob/main/intake.md",
};
