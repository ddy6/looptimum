export const navItems = [
  { href: "/", label: "Home" },
  { href: "/how-it-works/", label: "How It Works" },
  { href: "/use-cases/", label: "Use Cases" },
  { href: "/evidence/", label: "Evidence" },
  { href: "/larc/", label: "LARC" },
  { href: "/pilot/", label: "Pilot" },
];

export const siteConfig = {
  siteUrl: "https://looptimum.io",
  contactEmail: "contact@looptimum.com",
  contactHref: "mailto:contact@looptimum.com?subject=Looptimum%20pilot%20fit%20review",
  larcContactHref: "mailto:contact@looptimum.com?subject=Discuss%20a%20LARC%20project",
  ogImagePath: "/og-card.svg",
  headerLogoPath: "/brand/looptimum-header.png",
  brandBannerPath: "/brand/looptimum-hero.png",
};

export const larcProjectArchetypes = [
  {
    title: "Integrated technical systems",
    body:
      "Projects combining software, hardware, models, data, or human workflows where performance depends on how the pieces are designed together.",
  },
  {
    title: "Compute-limited concepts",
    body:
      "Architectures whose simulation, inference, training, or orchestration costs may prevent a credible implementation path.",
  },
  {
    title: "Scarce physical evaluation",
    body:
      "Experimental or laboratory systems where each measurement is slow, costly, constrained, or difficult to repeat.",
  },
  {
    title: "Unresolved development paths",
    body:
      "Technically plausible ideas that need their bottlenecks, evidence sequence, and feasibility milestones made explicit.",
  },
];

export const larcMethodSteps = [
  {
    title: "Scope",
    body: "Turn the broad concept into systems, dependencies, decisions, constraints, and open technical questions.",
  },
  {
    title: "Identify bottlenecks",
    body: "Determine which costs, resources, measurements, or architectural choices are most likely to control feasibility.",
  },
  {
    title: "Define optimization architecture",
    body: "Decide what should be optimized, at what level, and whether the problem should be staged, constrained, or decomposed.",
  },
  {
    title: "Design the evidence pathway",
    body: "Sequence models, benchmarks, experiments, or prototypes so each step reduces a meaningful uncertainty.",
  },
  {
    title: "Support implementation",
    body: "Translate favorable evidence into a credible technical roadmap, validation criteria, and the next build decision.",
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
      "Looptimum uses the campaign's completed results to select the next bounded candidate instead of scheduling a broad sweep.",
  },
  {
    title: "Evaluate",
    body:
      "Your evaluator runs where it already lives: cluster jobs, scripts, CI runners, solver hosts, or lab workflows.",
  },
  {
    title: "Ingest",
    body:
      "The result—or a declared failure—is recorded in local files so the campaign can resume after interruptions and preserve an auditable decision trail.",
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
    href: "/evidence/gpt-training/",
    linkLabel: "See the anonymized GPT example",
  },
  {
    title: "Operational process tuning",
    body:
      "Lab workflows, ETL processes, and production runbooks where throughput, quality, and cost need to be balanced under guardrails.",
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
  eyebrow: string;
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
    eyebrow: "Validated engineering campaign",
    title: "Fine-to-coarse simulation mesh search",
    summary:
      "A bounded engineering campaign paired its selected candidate with downstream solver and mesh-independence validation.",
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
    limitations: ["Domain-specific acceptance required a separate downstream solver pass."],
    cta: { href: "/pilot/", label: "Assess a similar pilot" },
  },
  {
    slug: "gpt-training",
    href: "/evidence/gpt-training/",
    eyebrow: "Anonymized ML campaign",
    title: "Guided GPT training-recipe search",
    summary:
      "Ten bounded evaluations tested four generic recipe controls while the training evaluator remained externally owned.",
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
      "Single-seed, small-budget campaign.",
      "Observed result only; no statistical-significance or global-optimum claim.",
    ],
    cta: { href: "/pilot/", label: "Assess a similar pilot" },
  },
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
  gptCaseStudy:
    "https://github.com/ddy6/looptimum/tree/main/docs/examples/gpt_training_campaign",
  pilot: "https://github.com/ddy6/looptimum/blob/main/PILOT.md",
  intake: "https://github.com/ddy6/looptimum/blob/main/intake.md",
};
