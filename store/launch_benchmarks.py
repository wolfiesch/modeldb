"""Self-reported launch benchmark tables -> `benchmark_result` rows.

`store.launch_registry` mints launch-window identity and keeps announcement prose
as `provider_blog` evidence. It deliberately does NOT write benchmark numbers,
because most launch posts publish them only as chart images.

This module handles the cases where a vendor DOES publish a machine-readable (or
vision-transcribable) eval table: Hugging Face model cards, API docs, and launch
posts with an explicit Evals section. Every row it writes carries
`self_reported = 1`, so independent aggregator rows (Artificial Analysis, Epoch,
SWE-bench, LMArena) always remain distinguishable in queries.

Editorial rules encoded here, per `.agents/skills/new-model-drop/rules/research.md`:

  1. A vendor table is authoritative only for the vendor's OWN models. Competitor
     columns are the vendor's measurement of somebody else's model, so they are
     preserved inside the snapshot payload as `comparison_only` and never become
     `benchmark_result` rows attributed to the other developer.
  2. Harness, reasoning effort, precision, and metric variant go in
     `eval_condition_json` - never into a new `benchmark` id and never into a new
     `model` row.
  3. Footnotes that define the eval condition are captured verbatim so a reader
     can tell "Terminal-Bench 2.1 under Claude Code avg@10" from
     "Terminal-Bench 2.1 under mini-swe-agent".
  4. Values are transcribed exactly as printed. `None` means the vendor printed
     "--", "-", or an em dash; no cell is inferred from a bar height.

Idempotent: each set is content-hashed. Re-running with unchanged data reuses the
snapshot and rewrites only that snapshot's rows.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3

from ingest.base import REPO_ROOT, utcnow

# ---------------------------------------------------------------------------
# Benchmark catalog: ids created or reused by the sets below.
# id -> (name, category, metric_default, higher_is_better, source_url)
# Existing ids are re-listed with INSERT OR IGNORE semantics so an established
# name/source_url is never overwritten by a launch-post spelling.
# ---------------------------------------------------------------------------
BENCHMARK_CATALOG: dict[str, tuple[str, str | None, str, int, str | None]] = {
    # --- xAI Grok 4.6 evals table ---
    "cursorbench_v3_2": ("CursorBench v3.2", "coding", "percent", 1,
                         "https://x.ai/news/grok-4-6"),
    "apex_agents": ("APEX-Agents", "agentic", "percent", 1,
                    "https://x.ai/news/grok-4-6"),
    "apex_swe": ("APEX-SWE", "coding", "percent", 1,
                 "https://x.ai/news/grok-4-6"),
    "terminal_bench_v3_0": ("Terminal-Bench v3.0", "agentic", "percent", 1,
                            "https://x.ai/news/grok-4-6"),
    "harvey_lab_vals": ("Harvey LAB (Vals)", "legal", "percent", 1,
                        "https://x.ai/news/grok-4-6"),
    # --- Alibaba Qwen3.8-Max card ---
    "nl2repo_bench": ("NL2Repo-Bench", "coding", "percent", 1,
                      "https://huggingface.co/Qwen/Qwen3.8-2.4T-A95B"),
    "frontierswe": ("FrontierSWE", "coding", "percent", 1,
                    "https://www.frontierswe.com"),
    "mls_bench_lite": ("MLS-Bench-Lite", "coding", "percent", 1, None),
    "paperbench": ("PaperBench", "research", "percent", 1, None),
    "androidbench": ("AndroidBench", "computer_use", "percent", 1, None),
    "qwen_swe_bench": ("QwenSWEBench", "coding", "percent", 1,
                       "https://huggingface.co/Qwen/Qwen3.8-2.4T-A95B"),
    "qwen_qoder_bench": ("QwenQoderBench", "coding", "percent", 1,
                         "https://huggingface.co/Qwen/Qwen3.8-2.4T-A95B"),
    "qwen_react_bench": ("QwenReactBench", "coding", "elo", 1,
                         "https://huggingface.co/Qwen/Qwen3.8-2.4T-A95B"),
    "qwen_svg_bench": ("QwenSVGBench", "coding", "elo", 1,
                       "https://huggingface.co/Qwen/Qwen3.8-2.4T-A95B"),
    "cowork_bench": ("CoWorkBench", "agentic", "percent", 1,
                     "https://huggingface.co/Qwen/Qwen3.8-2.4T-A95B"),
    "workspace_bench": ("WorkSpaceBench", "agentic", "percent", 1, None),
    "job_bench": ("JobBench", "agentic", "percent", 1, None),
    "skills_bench": ("SkillsBench", "agentic", "percent", 1, None),
    "widesearch": ("WideSearch", "agentic", "percent", 1, None),
    "onemillion_bench": ("$OneMillion-Bench", "general", "percent", 1, None),
    "plawbench": ("PLawBench", "legal", "percent", 1, None),
    "prbench_legal": ("PRBench-Legal", "legal", "percent", 1, None),
    "prbench_finance": ("PRBench-Finance", "finance", "percent", 1, None),
    "mrcr_v2_256k_8needle": ("MRCR v2 8-needle 256K", "long_context", "percent", 1, None),
    "longbench_v2": ("LongBench v2", "long_context", "percent", 1, None),
    # --- DeepSeek V4-Flash-0731 card ---
    "cybergym": ("Cybergym", "security", "percent", 1, None),
    "dsbench_fullstack": ("DSBench-FullStack", "coding", "percent", 1,
                          "https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731"),
    "dsbench_hard": ("DSBench-Hard", "coding", "percent", 1,
                     "https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731"),
    # --- Meta Muse Spark 1.2 launch charts ---
    "meta_internal_coding_bench": ("Meta Internal Coding Bench", "coding", "percent", 1,
                                   "https://research.meta.ai/blog/introducing-muse-code-and-muse-spark-1-2"),
    # --- Meta Muse Glimmer card ---
    "mcp_atlas": ("MCP Atlas (Public)", "agentic", "percent", 1, None),
    "deepsearch_qa": ("DeepSearch QA", "agentic", "percent", 1, None),
    "tau3_bench_banking": ("tau3-bench (Banking)", "agentic", "percent", 1, None),
    "wildclawbench": ("WildClawBench", "agentic", "percent", 1, None),
    "gaia2": ("GAIA2", "agentic", "percent", 1, None),
    "osworld_verified": ("OSWorld-Verified", "computer_use", "percent", 1, None),
    "charxiv_reasoning": ("CharXiv Reasoning", "multimodal", "percent", 1, None),
    "screenspot_pro": ("ScreenSpot Pro", "computer_use", "percent", 1, None),
    "omnidocbench_v1_5": ("OmniDocBench v1.5", "multimodal", "percent", 1, None),
    "aime_2026": ("AIME 2026", "math", "percent", 1, None),
    "beam128k": ("Beam128K", "long_context", "percent", 1, None),
    "ci_memories_violation": ("CI Memories (Violation)", "safety", "percent", 0, None),
    "ci_memories_coverage": ("CI Memories (Coverage)", "safety", "percent", 1, None),
    "siren_agentdojo_asr": ("Siren AgentDojo (Attack Success Rate)", "safety", "percent", 0, None),
    "siren_agentdojo_utility": ("Siren AgentDojo (Utility)", "safety", "percent", 1, None),
    "mbct": ("MBCT", "safety", "percent", 1, None),
    "hpct": ("HPCT", "safety", "percent", 1, None),
    "vct": ("VCT", "safety", "percent", 1, None),
    "wmdp_bio": ("WMDP (Bio)", "safety", "percent", 1, None),
    "wmdp_chem": ("WMDP (Chem)", "safety", "percent", 1, None),
    "labbench_protocolqa": ("Lab Bench (ProtocolQA)", "safety", "percent", 1, None),
    # --- NVIDIA Nemotron 3.5 Lightning card ---
    "aa_omniscience": ("AA-Omniscience", "knowledge", "score", 1, None),
    "swe_bench_multilingual": ("SWE-bench Multilingual", "coding", "percent", 1, None),
    "pinchbench": ("PinchBench", "agentic", "percent", 1, None),
    # --- OpenAI GPT-5.6-Cyber ---
    "advanced_cybersecurity_completion_rate": (
        "Advanced Cybersecurity Completion Rate", "security", "percent", 1,
        "https://openai.com/index/expanding-daybreak-as-the-cyber-defense-window-narrows/"),
    # --- Google Gemini 3.7 Flash ---
    "webdev_arena_elo": ("WebDev Arena", "coding", "elo", 1,
                         "https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-gemini-3-7-flash/"),
    "gdp_pdf": ("GDP.pdf", "reasoning", "percent", 1,
                "https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-gemini-3-7-flash/"),
    # --- Microsoft MAI-Thinking-1 ---
    "aime_2025": ("AIME 2025", "math", "percent", 1, None),
}

# Benchmark ids already in the catalog that these sets reuse. Listed for review
# clarity; `_upsert_benchmark_catalog` never mutates them.
REUSED_BENCHMARK_IDS = (
    "artificial_analysis_intelligence_index", "gdpval_aa_v2", "deepswe",
    "frontiercode_1_1", "artificial_analysis_briefcase", "swe_bench_pro",
    "swe_bench_verified", "gpqa_diamond", "mmlu_pro", "scicode",
    "terminalbench_v2_1", "toolathlon", "agents_last_exam", "automationbench",
    "mmmu_pro", "healthbench", "browsecomp", "hle", "ifbench", "lcr",
)

# ---------------------------------------------------------------------------
# Launch benchmark sets. `columns` mirrors the printed table column order;
# `None` marks a column that belongs to another developer (comparison only).
# ---------------------------------------------------------------------------
LAUNCH_BENCHMARK_SETS: tuple[dict, ...] = (
    {
        "set_id": "xai_grok_4_6_evals",
        "source_id": "provider_blog",
        "url": "https://x.ai/news/grok-4-6",
        "published_at": "2026-08-12",
        "columns": (
            {"label": "Grok 4.6 High", "model_slug": "xai/grok-4.6",
             "condition": {"reasoning_effort": "high"}},
            {"label": "Grok 4.5 High", "model_slug": "xai/grok-4.5",
             "condition": {"reasoning_effort": "high"}},
            {"label": "GPT-5.6 Sol Max", "model_slug": None},
            {"label": "Fable 5 Max", "model_slug": None},
        ),
        "table_notes": (
            "Best score per evaluation in bold. Third-party model scores are the "
            "best of self-reported or publicly available results.",
            "Competitor figures are drawn from the respective developers' published "
            "system cards or benchmark leaderboards.",
        ),
        "rows": (
            ("artificial_analysis_intelligence_index", "AA Intelligence Index", "index",
             (61, 56, 61, 62), {}),
            ("gdpval_aa_v2", "GDPVal-AA v2", "score", (1753, 1526, 1728, 1741), {}),
            ("cursorbench_v3_2", "CursorBench v3.2", "percent",
             (69.9, 66.7, 67.2, 70.5), {}),
            ("deepswe", "DeepSWE v1.1", "percent", (65.9, 54.0, 73.0, 70.0),
             {"version": "1.1"}),
            ("frontiercode_1_1", "FrontierCode v1.1 (Extended)", "percent",
             (61.3, 56.6, 60.6, 63.6), {"split": "extended"}),
            ("apex_agents", "APEX-Agents", "percent", (57.5, 47.1, 56.7, 59.2), {}),
            ("terminal_bench_v3_0", "Terminal-Bench v3.0", "percent",
             (26.0, 15.7, 34.6, 34.1), {}),
            ("apex_swe", "APEX-SWE", "percent", (56.4, 53.6, None, 58.8), {}),
            ("artificial_analysis_briefcase", "AA-Briefcase", "score",
             (1577, 1313, 1502, 1574), {}),
            ("harvey_lab_vals", "Harvey LAB (Vals)", "percent",
             (15.8, 12.9, 2.5, 11.3), {}),
        ),
    },
    {
        "set_id": "alibaba_qwen3_8_max_card",
        "source_id": "hf_model_card",
        "url": "https://huggingface.co/Qwen/Qwen3.8-2.4T-A95B",
        "published_at": "2026-08-12",
        "columns": (
            {"label": "Opus 4.8", "model_slug": None},
            {"label": "Fable 5", "model_slug": None},
            {"label": "GPT 5.6 Sol (max)", "model_slug": None},
            {"label": "Qwen3.7-Max", "model_slug": "alibaba/qwen3.7-max", "condition": {}},
            {"label": "Qwen3.8-Max", "model_slug": "alibaba/qwen3.8-max", "condition": {}},
        ),
        "table_notes": (
            "Fable5 results may involve fallbacks.",
            "Empty cells (--): Scores are not yet available or are not applicable.",
        ),
        "rows": (
            ("terminalbench_v2_1", "Terminal Bench 2.1", "percent",
             (84.6, 84.6, 88.8, 74.5, 86.6),
             {"section": "Coding Agent", "harness": "Claude Code", "aggregation": "avg@10",
              "timeout": "5 hours", "max_tokens": 131072,
              "note": "Evaluated with Claude Code (avg@10), using a 5-hour timeout and "
                      "max_tokens=131,072. For all other models, we report the best "
                      "published score across harnesses."}),
            ("swe_bench_pro", "SWE-bench Pro", "percent",
             (69.2, 80.0, 64.6, 60.6, 67.7),
             {"section": "Coding Agent", "harness": "Claude Code", "temperature": 1.0,
              "top_p": 0.95, "context_window": "256K",
              "note": "Problematic tasks corrected and all baselines evaluated on the "
                      "refined benchmark."}),
            ("deepswe", "DeepSWE 1.1", "percent",
             (59.0, 70.0, 73.0, 21.6, 56.6),
             {"section": "Coding Agent", "version": "1.1",
              "harness": "best of Claude Code and mini-SWE-agent", "temperature": 1.0,
              "top_p": 0.95, "context_window": "256K",
              "note": "We report the highest score among both harnesses; notably, "
                      "Qwen3.8-Max performs best on Claude Code."}),
            ("nl2repo_bench", "NL2Repo-Bench", "percent",
             (69.4, None, None, 47.2, 55.9),
             {"section": "Coding Agent", "harness": "Claude Code",
              "note": "To prevent reward hacking, we disable Bash commands that attempt "
                      "to access the specific repository, such as pip download, pip "
                      "install, and git clone."}),
            ("frontierswe", "FrontierSWE", "percent",
             (70.0, 88.8, None, 40.7, 73.5),
             {"section": "Coding Agent", "harness": "Claude Code", "aggregation": "MEAN@5",
              "note": "All other available MEAN@5 results are taken from the official "
                      "FrontierSWE leaderboard as of August 3, 2026. Dominance scores are "
                      "recomputed from the raw scores using the official evaluation script."}),
            ("mls_bench_lite", "MLS-Bench-Lite", "percent",
             (42.8, 49.9, 46.2, 31.7, 41.0),
             {"section": "Coding Agent", "harness": "Claude Code", "timeout": "5 hours",
              "max_tokens": 131072,
              "note": "All other model scores are taken from the official leaderboard."}),
            ("paperbench", "PaperBench", "percent",
             (80.3, 88.8, 90.5, 64.8, 93.0),
             {"section": "Coding Agent", "setting": "BasicAgent, Code-Dev mode",
              "judge": "Claude Opus 4.6", "aggregation": "avg@3",
              "note": "Max 12 hours per run."}),
            ("androidbench", "AndroidBench", "percent",
             (69.8, 84.5, 74.0, 56.5, 75.1),
             {"section": "Coding Agent", "split": "95-task public subset",
              "aggregation": "avg@3"}),
            ("qwen_swe_bench", "QwenSWEBench", "percent",
             (84.0, 86.3, 73.5, 63.4, 80.7),
             {"section": "Coding Agent", "inhouse": True, "harness": "Claude Code",
              "aggregation": "avg@3", "timeout": "8 hours", "max_tokens": 32768,
              "temperature": 1.0, "context_window": "256K"}),
            ("qwen_qoder_bench", "QwenQoderBench", "percent",
             (62.7, 63.1, 53.8, 36.8, 58.4),
             {"section": "Coding Agent", "inhouse": True, "harness": "Claude Code",
              "aggregation": "avg@5", "timeout": "6 hours", "max_tokens": 32768,
              "temperature": 1.0, "context_window": "256K"}),
            ("qwen_react_bench", "QwenReactBench", "elo",
             (1694, 1770, 1564, 1538, 1724),
             {"section": "Coding Agent", "inhouse": True, "harness": "Claude Code",
              "note": "Bilingual (EN/CN), 7 categories; auto-render + multimodal judge; "
                      "BT/Elo rating."}),
            ("qwen_svg_bench", "QwenSVGBench", "elo",
             (1648, 1690, 1758, 1499, 1713),
             {"section": "Coding Agent", "inhouse": True,
              "note": "Bilingual (EN/CN), auto-render + multimodal judge; BT/Elo rating."}),
            ("cowork_bench", "CoWorkBench", "percent",
             (72.3, 75.9, 71.5, 64.6, 74.8),
             {"section": "General Agent", "inhouse": True,
              "note": "Long-horizon tasks across computer science, finance, law, medical, "
                      "and other productivity domains."}),
            ("workspace_bench", "WorkSpaceBench", "percent",
             (66.8, 68.7, 65.6, 61.4, 67.7), {"section": "General Agent"}),
            ("job_bench", "JobBench", "percent",
             (48.4, 57.4, 45.4, 31.3, 53.4), {"section": "General Agent"}),
            ("skills_bench", "SkillsBench", "percent",
             (65.1, 70.9, 73.5, 61.2, 70.2),
             {"section": "General Agent", "version": "v1.1", "tasks": 87,
              "aggregation": "avg@3", "harness": "OpenCode (Qwen series)",
              "note": "Opus 4.8 and Fable 5 are evaluated on Claude Code; GPT-5.6 Sol is "
                      "evaluated on Codex; the Qwen-series are evaluated on OpenCode. All "
                      "results are from our own testing."}),
            ("agents_last_exam", "Agents' Last Exam (Pass)", "pass_percent",
             (27.0, None, 30.6, 11.8, 27.0), {"section": "General Agent", "metric_variant": "Pass"}),
            ("agents_last_exam", "Agents' Last Exam (Score)", "score",
             (45.1, None, 53.6, 31.1, 52.4), {"section": "General Agent", "metric_variant": "Score"}),
            ("automationbench", "Automation-Bench (Pass@1)", "pass@1",
             (27.2, 29.1, 29.7, 14.2, 27.3),
             {"section": "General Agent", "split": "600-task public subset"}),
            ("toolathlon", "Toolathlon Verified (Pass@1)", "pass@1",
             (76.2, 77.9, 74.9, 49.7, 72.5), {"section": "General Agent", "split": "Verified"}),
            ("widesearch", "WideSearch", "percent",
             (72.9, 81.2, None, 75.2, 81.9),
             {"section": "General Agent", "harness": "Qwen-Agent (ours) / Claude Code (external)",
              "metric_variant": "average item-F1 over four runs"}),
            ("hle", "HLE w/ tools", "percent",
             (57.9, 64.5, 58.0, 53.5, 56.2), {"section": "General Agent", "tools": True}),
            ("gpqa_diamond", "GPQA Diamond", "percent",
             (92.0, 92.6, 94.1, 92.4, 92.6), {"section": "General Capabilities"}),
            ("hle", "HLE", "percent",
             (45.7, 53.3, 47.2, 41.4, 43.6), {"section": "General Capabilities", "tools": False}),
            ("ifbench", "IFBench", "percent",
             (62.2, 63.5, 72.7, 79.1, 82.8), {"section": "General Capabilities"}),
            ("onemillion_bench", "$OneMillion-Bench (expert score)", "expert_score",
             (41.8, 55.9, 53.8, 44.4, 52.5),
             {"section": "General Capabilities", "judge": "gemini-3.1-pro-preview"}),
            ("healthbench", "HealthBench", "percent",
             (52.4, None, 55.3, 54.5, 60.2), {"section": "General Capabilities"}),
            ("plawbench", "PLawBench", "percent",
             (69.6, 70.2, 72.3, 58.9, 73.2),
             {"section": "General Capabilities", "judge": "gemini-3.1-pro-preview"}),
            ("prbench_legal", "PRBench-Legal", "percent",
             (52.7, 57.6, 57.6, 48.5, 57.6), {"section": "General Capabilities"}),
            ("prbench_finance", "PRBench-Finance", "percent",
             (51.9, 55.8, 55.5, 46.8, 58.3), {"section": "General Capabilities"}),
            ("mrcr_v2_256k_8needle", "MRCR v2 256K (8-needle)", "percent",
             (83.2, None, 93.8, 86.7, 92.9), {"section": "General Capabilities"}),
            ("longbench_v2", "LongBench v2", "percent",
             (69.1, None, 67.1, 65.3, 66.3), {"section": "General Capabilities"}),
        ),
    },
    {
        "set_id": "deepseek_v4_flash_0731_card",
        "source_id": "hf_model_card",
        "url": "https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731",
        "published_at": "2026-07-31",
        "columns": (
            {"label": "DeepSeek-V4-Flash-0731", "model_slug": "deepseek/deepseek-v4-flash-0731",
             "condition": {"reasoning_effort": "max"}},
            {"label": "DeepSeek-V4-Flash (Preview)", "model_slug": "deepseek/deepseek-v4-flash",
             "condition": {"build": "preview"}},
            {"label": "DeepSeek-V4-Pro (Preview)", "model_slug": "deepseek/deepseek-v4-pro",
             "condition": {"build": "preview"}},
            {"label": "GLM-5.2", "model_slug": None},
            {"label": "Opus-4.8", "model_slug": None},
        ),
        "table_notes": (
            "For the Code Agent tasks among the public benchmarks above, "
            "DeepSeek-V4-Flash-0731 is evaluated with the minimal mode of DeepSeek "
            "Harness (to be released) as the agent framework, using the `max` reasoning "
            "effort level with temperature = 1.0, top_p = 0.95.",
            "DSBench-FullStack is an internal full-stack development test set; "
            "DSBench-Hard is an internal test set of difficult coding-agent problems.",
        ),
        "rows": (
            ("terminalbench_v2_1", "Terminal Bench 2.1", "percent",
             (82.7, 61.8, 72.1, 81.0, 85.0), {"harness": "DeepSeek Harness (minimal mode)"}),
            ("nl2repo_bench", "NL2Repo", "percent",
             (54.2, 39.4, 38.5, 48.9, 69.7), {"harness": "DeepSeek Harness (minimal mode)"}),
            ("cybergym", "Cybergym", "percent",
             (76.7, 38.7, 52.7, None, 83.1), {"harness": "DeepSeek Harness (minimal mode)"}),
            ("deepswe", "DeepSWE", "percent",
             (54.4, 7.3, 12.8, 46.2, 58.0), {"harness": "DeepSeek Harness (minimal mode)"}),
            ("toolathlon", "Toolathlon-Verified", "percent",
             (70.3, 49.7, 55.9, 59.9, 76.2), {"split": "Verified"}),
            ("agents_last_exam", "Agents' Last Exam", "percent",
             (25.2, 15.8, 16.5, 23.8, 25.7), {}),
            ("automationbench", "AutomationBench Public", "percent",
             (25.1, 10.8, 12.8, 12.9, 27.2), {"split": "public"}),
            ("dsbench_fullstack", "DSBench-FullStack", "percent",
             (68.7, 37.0, 41.8, 61.8, 71.6), {"inhouse": True}),
            ("dsbench_hard", "DSBench-Hard", "percent",
             (59.6, 25.8, 31.1, 54.5, 71.7), {"inhouse": True}),
        ),
    },
    {
        "set_id": "meta_muse_spark_1_2_charts",
        "source_id": "provider_blog",
        "url": "https://research.meta.ai/blog/introducing-muse-code-and-muse-spark-1-2",
        "published_at": "2026-08-05",
        "columns": (
            {"label": "Muse Spark 1.2 (Muse Code)", "model_slug": "meta/muse-spark-1.2",
             "condition": {"harness": "Muse Code"}},
            {"label": "Muse Spark 1.1 (mini-swe-agent)", "model_slug": "meta/muse-spark-1.1",
             "condition": {"harness": "mini-swe-agent"}},
        ),
        "table_notes": (
            "Values transcribed from the launch post's bar-chart images; the charts print "
            "each value above its bar. The post publishes no footnote for pass count or "
            "eval conditions beyond the per-bar harness sub-label.",
            "Competitor bars (Opus 5 max/Claude Code, GPT 5.6 Terra max/Codex, "
            "Grok 4.5 high/Grok Build, Gemini 3.6 Flash high/Antigravity CLI) are Meta's "
            "measurement of other developers' models and are preserved as comparison only.",
        ),
        "rows": (
            ("terminalbench_v2_1", "Terminal-Bench 2.1", "percent", (82.9, 76.2),
             {"evidence": "chart image"}),
            ("deepswe", "DeepSWE 1.1", "percent", (59.3, 53.0),
             {"version": "1.1", "evidence": "chart image"}),
            ("meta_internal_coding_bench", "Meta Internal Coding Bench", "percent",
             (70.6, 68.3), {"inhouse": True, "evidence": "chart image"}),
        ),
        "comparison_only": {
            "Terminal-Bench 2.1": {"Opus 5 (max) / Claude Code": 86.7,
                                   "GPT 5.6 Terra (max) / Codex": 81.8,
                                   "Grok 4.5 (high) / Grok Build": 81.6,
                                   "Gemini 3.6 Flash (high) / Antigravity CLI": 78.9},
            "DeepSWE 1.1": {"Opus 5 (max) / Claude Code": 65.0,
                            "GPT 5.6 Terra (max) / Codex": 64.8,
                            "Grok 4.5 (high) / Grok Build": 56.6,
                            "Gemini 3.6 Flash (high) / Antigravity CLI": 40.0},
            "Meta Internal Coding Bench": {"Opus 5 (max)": 79.4,
                                           "GPT 5.6 Terra (max)": 65.4,
                                           "Gemini 3.6 Flash (high)": 63.9},
        },
    },
    {
        "set_id": "meta_muse_glimmer_30b_card",
        "source_id": "hf_model_card",
        "url": "https://huggingface.co/meta-models/Muse-Glimmer-30B",
        "published_at": "2026-08-10",
        "columns": (
            {"label": "Muse Glimmer-30B High Reasoning", "model_slug": "meta/muse-glimmer-30b",
             "condition": {"reasoning_strength": "high"}},
            {"label": "Gemma4-31B Thinking Mode", "model_slug": None},
            {"label": "Qwen3.6-27B Thinking Mode", "model_slug": None},
        ),
        "table_notes": (
            "Compared with Gemma4-31B and Qwen3.6-27B, Muse Glimmer performs strongly for "
            "its size class on several widely used LLM benchmarks.",
            "For more detail about our evaluations, see "
            "https://research.meta.ai/static/muse-glimmer-methodology",
        ),
        "rows": (
            ("mcp_atlas", "MCP Atlas (Public)", "percent", (75.5, 54.2, 62.5),
             {"section": "General Agentic"}),
            ("deepsearch_qa", "DeepSearch QA", "percent", (74.6, 61.7, 71.1),
             {"section": "General Agentic"}),
            ("tau3_bench_banking", "tau3-Banking", "percent", (23.5, 15.1, 16.7),
             {"section": "General Agentic"}),
            ("wildclawbench", "WildClawBench", "percent", (47.6, 37.6, 43.2),
             {"section": "General Agentic"}),
            ("gdpval_aa_v2", "GDPVal-AA v2", "score", (953, 811, 1141),
             {"section": "General Agentic"}),
            ("gaia2", "Gaia2", "percent", (43.3, 36.4, 40.0),
             {"section": "General Agentic"}),
            ("skills_bench", "SkillsBench (with skills)", "percent", (44.3, 32.4, 46.6),
             {"section": "General Agentic", "skills": True}),
            ("osworld_verified", "OSWorld-Verified", "percent", (65.9, 58.5, 75.6),
             {"section": "General Agentic"}),
            ("swe_bench_pro", "SWE-Bench Pro", "percent", (51.2, 36.9, 50.2),
             {"section": "Agentic Coding"}),
            ("swe_bench_verified", "SWE-Bench Verified", "percent", (76.0, 66.6, 77.2),
             {"section": "Agentic Coding"}),
            ("terminalbench_v2_1", "TerminalBench 2.1 (with terminus2)", "percent",
             (51.7, 43.4, 60.7), {"section": "Agentic Coding", "harness": "terminus2"}),
            ("scicode", "SciCode", "percent", (43.6, 43.4, 39.8),
             {"section": "Agentic Coding"}),
            ("charxiv_reasoning", "Charxiv Reasoning", "percent", (78.8, 77.7, 78.4),
             {"section": "Multimodal"}),
            ("screenspot_pro", "ScreenSpot Pro", "percent", (75.4, 75.9, 76.1),
             {"section": "Multimodal"}),
            ("omnidocbench_v1_5", "OmniDocBench v1.5", "percent", (75.8, 72.5, 77.8),
             {"section": "Multimodal"}),
            ("mmmu_pro", "MMMU Pro", "percent", (74, 73, 75), {"section": "Multimodal"}),
            ("ci_memories_violation", "CI Memories - Violation", "percent",
             (26.4, 12.1, 53.4), {"section": "Security and Privacy", "direction": "lower is better"}),
            ("ci_memories_coverage", "CI Memories - Coverage", "percent",
             (64.8, 53.0, 66.9), {"section": "Security and Privacy"}),
            ("siren_agentdojo_asr", "Siren AgentDojo - Attack Success Rate", "percent",
             (28.4, 25.6, 40.3), {"section": "Security and Privacy", "direction": "lower is better"}),
            ("siren_agentdojo_utility", "Siren AgentDojo - Utility", "percent",
             (94.2, 90.8, 92.7), {"section": "Security and Privacy"}),
            ("ifbench", "IFBench", "percent", (77.0, 76.0, 70.8),
             {"section": "General Capabilities and Reasoning"}),
            ("aime_2026", "AIME 2026", "percent", (94.7, 89.2, 94.1),
             {"section": "General Capabilities and Reasoning"}),
            ("gpqa_diamond", "GPQA Diamond (AA)", "percent", (83.5, 85.7, 84.2),
             {"section": "General Capabilities and Reasoning", "implementation": "Artificial Analysis"}),
            ("hle", "HLE Text (AA)", "percent", (22.0, 23.6, 23.1),
             {"section": "General Capabilities and Reasoning", "modality": "text",
              "implementation": "Artificial Analysis"}),
            ("lcr", "AA-LCR", "percent", (80.0, 68.3, 73.3),
             {"section": "General Capabilities and Reasoning"}),
            ("beam128k", "Beam128K", "percent", (65.1, 58.2, 63.0),
             {"section": "General Capabilities and Reasoning"}),
        ),
    },
    {
        "set_id": "meta_muse_glimmer_30b_card_safety",
        "source_id": "hf_model_card",
        "url": "https://huggingface.co/meta-models/Muse-Glimmer-30B#safety",
        "published_at": "2026-08-10",
        "columns": (
            {"label": "Muse Glimmer-30B", "model_slug": "meta/muse-glimmer-30b", "condition": {}},
            {"label": "Gemma4-31B", "model_slug": None},
            {"label": "Qwen3.6-27B", "model_slug": None},
            {"label": "Kimi K3", "model_slug": None},
        ),
        "table_notes": (
            "Dual-use hazardous-capability proxies from the model card's trust and safety "
            "section. A higher score means more hazardous-domain knowledge, so a higher "
            "value is not a product win; it is an uplift-risk signal.",
        ),
        "rows": (
            ("mbct", "MBCT", "percent", (41.5, 50.6, 45.9, 58.9), {"uplift_proxy": True}),
            ("hpct", "HPCT", "percent", (52.3, 54.0, 48.7, 59.6), {"uplift_proxy": True}),
            ("vct", "VCT", "percent", (37.0, 43.5, 33.7, 48.0), {"uplift_proxy": True}),
            ("wmdp_bio", "WMDP (Bio)", "percent", (86.5, 85.9, 84.8, 89.1), {"uplift_proxy": True}),
            ("wmdp_chem", "WMDP (Chem)", "percent", (75.2, 80.5, 74.8, 84.2), {"uplift_proxy": True}),
            ("labbench_protocolqa", "Lab Bench (ProtocolQA)", "percent",
             (80.2, 75.8, 69.1, 81.9), {"uplift_proxy": True}),
        ),
    },
    {
        "set_id": "nvidia_nemotron_3_5_lightning_card",
        "source_id": "hf_model_card",
        "url": "https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16",
        "published_at": "2026-08-11",
        "columns": (
            {"label": "Nemotron-3.5-Lightning-30B-A3B-BF16",
             "model_slug": "nvidia/nemotron-3.5-lightning", "condition": {"precision": "BF16"}},
            {"label": "Qwen 3.6 35B A3B", "model_slug": None},
            {"label": "Gemma 4 26B A4B", "model_slug": None},
            {"label": "Nemotron 3 Nano", "model_slug": "nvidia/nvidia/nemotron-3-nano-30b-a3b",
             "condition": {}},
            {"label": "Nemotron 3 Super", "model_slug": "nvidia/nvidia/nemotron-3-super-120b-a12b",
             "condition": {}},
            {"label": "GPT-OSS 20B", "model_slug": None},
        ),
        "table_notes": (
            "Accuracy numbers measured by NVIDIA under a consistent harness (NeMo Gym / "
            "Nemo Evaluator SDK); they may differ from vendors' self-reported numbers.",
            "Most evaluations use NeMo Gym-native harnesses while a small subset, including "
            "SWE-Bench and Terminal-Bench, used NeMo Evaluator natively. Recipes: "
            "https://github.com/NVIDIA-NeMo/Gym/tree/main/nemotron_recipes/lightning-3.5/reproducibility.md",
        ),
        "row_condition": {"harness": "NeMo Gym / Nemo Evaluator SDK"},
        "rows": (
            ("mmlu_pro", "MMLU Pro", "percent", (81.94, 85.63, 85.20, 78.46, 83.89, 76.40),
             {"section": "General Knowledge"}),
            ("aa_omniscience", "AA-Omniscience", "score",
             (17.50, 19.47, 22.17, 20.15, 26.68, 16.62), {"section": "General Knowledge"}),
            ("gpqa_diamond", "GPQA Diamond (no tools)", "percent",
             (75.44, 83.40, 79.61, 74.05, 78.60, 71.46), {"section": "Reasoning", "tools": False}),
            ("hle", "HLE (text-only, no tools)", "percent",
             (11.72, 19.56, 17.42, 10.89, 20.30, 13.76),
             {"section": "Reasoning", "modality": "text", "tools": False}),
            ("scicode", "SciCode", "percent",
             (32.60, 35.33, 40.28, 30.08, 35.11, 38.63), {"section": "Reasoning"}),
            ("swe_bench_verified", "SWE-bench Verified", "percent",
             (51.56, 70.12, 57.40, 34.08, 63.08, 52.44),
             {"section": "Coding & Agentic", "harness": "NeMo Evaluator"}),
            ("swe_bench_multilingual", "SWE-bench Multilingual", "percent",
             (39.33, 63.40, 43.40, 14.07, 49.80, 41.93), {"section": "Coding & Agentic"}),
            ("terminalbench_v2_1", "Terminal-Bench 2.1", "percent",
             (24.58, 44.38, 37.22, 8.29, 39.61, 15.17),
             {"section": "Coding & Agentic", "harness": "NeMo Evaluator"}),
            ("pinchbench", "PinchBench", "percent",
             (85.37, 88.07, 74.70, 66.11, 80.36, 57.20), {"section": "Coding & Agentic"}),
            ("browsecomp", "BrowseComp", "percent",
             (36.97, 48.74, 26.30, 13.74, 22.77, None), {"section": "Coding & Agentic"}),
            ("tau3_bench_banking", "tau3-bench (Banking)", "percent",
             (9.28, 10.52, 14.02, 7.01, 12.37, None), {"section": "Coding & Agentic"}),
            ("gdpval_aa_v2", "GDPval-AA-V2", "score",
             (832, 1015, 807, 473, 746, None), {"section": "Coding & Agentic"}),
            ("ifbench", "IFBench (loose)", "percent",
             (71.88, 63.71, 77.25, 72.17, 71.92, 68.50),
             {"section": "Instruction Following", "metric_variant": "loose"}),
            ("lcr", "AA-LCR", "percent",
             (52.00, 61.06, 57.56, 32.75, 58.44, 32.88), {"section": "Long Context"}),
        ),
    },
    {
        "set_id": "nvidia_nemotron_3_5_lightning_nvfp4_chart",
        "source_id": "hf_model_card",
        "url": "https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16#accuracy-plot",
        "published_at": "2026-08-11",
        "columns": (
            {"label": "Nemotron-3.5-Lightning-30B-A3B-NVFP4",
             "model_slug": "nvidia/nemotron-3.5-lightning", "condition": {"precision": "NVFP4"}},
            {"label": "Nemotron-3-Nano-30B-A3B-NVFP4",
             "model_slug": "nvidia/nvidia/nemotron-3-nano-30b-a3b",
             "condition": {"precision": "NVFP4"}},
            {"label": "Qwen-3.6-35B-A3B", "model_slug": None},
            {"label": "Gemma-4-26B-A4B-it", "model_slug": None},
        ),
        "table_notes": (
            "Chart footnote: Competitor accuracy measured by NVIDIA under a consistent "
            "harness; Lightning shown as NVFP4.",
            "Values transcribed from the card's accuracy_plot.png data labels. These are the "
            "NVFP4-quantized measurements of the same canonical model, so they differ "
            "slightly from the BF16 reference table.",
        ),
        "row_condition": {"harness": "NeMo Gym / Nemo Evaluator SDK", "evidence": "chart image"},
        "rows": (
            ("ifbench", "IFBench (Inst. Follow.)", "percent", (72.9, 72.2, 63.7, 77.2), {}),
            ("swe_bench_verified", "SWE-Bench (Coding)", "percent", (52.8, 34.1, 70.1, 57.4), {}),
            ("hle", "HLE (Science)", "percent", (10.5, 10.9, 19.6, 17.4), {}),
            ("terminalbench_v2_1", "Terminal-Bench (Terminal)", "percent",
             (23.5, 8.3, 44.4, 37.2), {}),
            ("tau3_bench_banking", "tau3-bench (Tool Use)", "percent", (9.5, 7.0, 10.5, 14.0), {}),
            ("lcr", "AA-LCR (Long Ctx)", "percent", (49.2, 32.8, 61.1, 57.6), {}),
        ),
    },
    {
        "set_id": "nvidia_nemotron_3_5_lightning_harness_sweep",
        "source_id": "hf_model_card",
        "url": "https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16#agentic-coding-benchmarks",
        "published_at": "2026-08-11",
        "columns": (
            {"label": "Nemotron-3.5-Lightning-30B-A3B",
             "model_slug": "nvidia/nemotron-3.5-lightning", "condition": {}},
        ),
        "table_notes": (
            "Chart note: Scores were obtained using unmodified harness system prompts and "
            "standard harness configurations.",
            "Harness-level sweep of one model, transcribed from "
            "agentic_coding_benchmarks.png. SWE-Bench Verified panel covers 500 tasks; "
            "Terminal-Bench 2.1 panel covers 89 tasks.",
        ),
        "row_condition": {"evidence": "chart image"},
        "rows": tuple(
            (bench_id, f"{label} ({harness} {version})", "percent", (score,),
             {"harness": harness, "harness_version": version, "tasks": tasks})
            for bench_id, label, tasks, harness, version, score in (
                ("swe_bench_verified", "SWE-Bench Verified", 500, "OpenCode", "v1.17.8", 60.0),
                ("swe_bench_verified", "SWE-Bench Verified", 500, "Copilot", "v1.0.71", 58.4),
                ("swe_bench_verified", "SWE-Bench Verified", 500, "Claude", "v2.1.126", 57.4),
                ("swe_bench_verified", "SWE-Bench Verified", 500, "Pi", "v0.80.10", 54.5),
                ("swe_bench_verified", "SWE-Bench Verified", 500, "Mini-SWE agent", "v2.4.5", 50.7),
                ("swe_bench_verified", "SWE-Bench Verified", 500, "OpenHands", "v1.36.1", 48.7),
                ("swe_bench_verified", "SWE-Bench Verified", 500, "Hermes", "v0.18.2", 45.7),
                ("swe_bench_verified", "SWE-Bench Verified", 500, "Codex", "v0.144.6", 11.0),
                ("terminalbench_v2_1", "Terminal-Bench 2.1", 89, "Mini-SWE agent", "v2.4.5", 29.7),
                ("terminalbench_v2_1", "Terminal-Bench 2.1", 89, "OpenCode", "v1.17.8", 29.1),
                ("terminalbench_v2_1", "Terminal-Bench 2.1", 89, "Claude", "v2.1.126", 29.0),
                ("terminalbench_v2_1", "Terminal-Bench 2.1", 89, "Copilot", "v1.0.71", 27.0),
                ("terminalbench_v2_1", "Terminal-Bench 2.1", 89, "OpenHands", "v1.36.1", 26.1),
                ("terminalbench_v2_1", "Terminal-Bench 2.1", 89, "Hermes", "v0.18.2", 25.8),
                ("terminalbench_v2_1", "Terminal-Bench 2.1", 89, "Pi", "v0.80.10", 24.5),
                ("terminalbench_v2_1", "Terminal-Bench 2.1", 89, "Codex", "v0.144.6", 2.9),
            )
        ),
    },
    {
        "set_id": "openai_gpt_5_6_cyber_completion_rate",
        "source_id": "provider_blog",
        "url": "https://openai.com/index/expanding-daybreak-as-the-cyber-defense-window-narrows/",
        "published_at": "2026-08-10",
        "columns": (
            {"label": "GPT-5.6-Cyber (Daybreak Red)", "model_slug": "openai/gpt-5.6-cyber",
             "condition": {"access_tier": "Daybreak Red"}},
            {"label": "GPT-5.6 Sol", "model_slug": "openai/gpt-5.6-sol", "condition": {}},
            {"label": "GPT-5.6 Sol (Daybreak Blue)", "model_slug": "openai/gpt-5.6-sol",
             "condition": {"access_tier": "Daybreak Blue"}},
        ),
        "table_notes": (
            "Verbatim: \"we created an internal evaluation (Advanced Cybersecurity "
            "Completion Rate) that measures how often models will respond to requests "
            "involving exploit-chain development, authentication bypass, privilege "
            "escalation, and other advanced cybersecurity scenarios. GPT-5.6-Cyber "
            "completes 95.0% of these requests, compared with just 1.5% for GPT-5.6 Sol, "
            "and 2.0% when used with Daybreak Blue access.\"",
            "This is a refusal-rate measurement, not a capability score. The post's "
            "ExploitGym and ExploitBench results are described only qualitatively "
            "(\"outperforms\", \"performs best\") with no printed numbers, so they are not "
            "recorded as benchmark_result rows. A system card is promised later.",
        ),
        "rows": (
            ("advanced_cybersecurity_completion_rate",
             "Advanced Cybersecurity Completion Rate", "percent", (95.0, 1.5, 2.0),
             {"inhouse": True,
              "note": "Measures willingness to complete advanced cybersecurity requests, "
                      "not task success."}),
        ),
    },
    {
        "set_id": "google_gemini_3_7_flash_evals",
        "source_id": "provider_blog",
        "url": "https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-gemini-3-7-flash/",
        "published_at": "2026-08-13",
        "columns": (
            {"label": "Gemini 3.7 Flash", "model_slug": "google/gemini-3.7-flash", "condition": {}},
            {"label": "Gemini 3.6 Flash", "model_slug": "google/gemini-3.6-flash", "condition": {}},
        ),
        "table_notes": (
            "Self-reported benchmarks from Google DeepMind Gemini 3.7 Flash launch post. "
            "FrontierCode 1.1 measured on Main split; DeepSWE measured on v1.1.",
        ),
        "rows": (
            ("frontiercode_1_1", "FrontierCode 1.1 (Main)", "percent", (43.6, 34.4), {"split": "main"}),
            ("deepswe", "DeepSWE v1.1", "percent", (65.3, 49.0), {"version": "1.1"}),
            ("webdev_arena_elo", "WebDev Arena", "elo", (1588.0, 1538.0), {}),
            ("gdp_pdf", "GDP.pdf", "percent", (34.0, 22.0), {}),
            ("automationbench", "AutomationBench", "percent", (30.4, 17.0), {}),
        ),
    },
    {
        "set_id": "microsoft_mai_thinking_1_evals",
        "source_id": "provider_blog",
        "url": "https://microsoft.ai/news/introducing-mai-thinking-1/",
        "published_at": "2026-08-12",
        "columns": (
            {"label": "MAI-Thinking-1", "model_slug": "microsoft/mai-thinking-1", "condition": {}},
        ),
        "table_notes": (
            "Self-reported reasoning and coding evaluations from Microsoft AI MAI-Thinking-1 announcement.",
        ),
        "rows": (
            ("aime_2025", "AIME 2025", "percent", (97.0,), {}),
            ("aime_2026", "AIME 2026", "percent", (94.5,), {}),
            ("swe_bench_pro", "SWE-bench Pro", "percent", (53.0,), {}),
        ),
    },
)

# Releases whose launch material publishes no numeric evals at all. Recorded so a
# later pass can tell "not yet published" from "not yet ingested".
KNOWN_BENCHMARK_GAPS: tuple[dict[str, str], ...] = (
    {
        "canonical_slug": "deepseek/deepseek-v4-pro-0813",
        "reason": "The GA 0813 build shipped without a launch post or an updated model "
                  "card; huggingface.co/deepseek-ai/DeepSeek-V4-Pro still serves the V4 "
                  "preview card, whose numbers belong to deepseek/deepseek-v4-pro. "
                  "DeepSeek states its in-house harness will be published later.",
        "revisit": "Watch for a DeepSeek-V4-Pro-0813 model card or a DeepSeek Harness "
                   "release, and for Artificial Analysis / SWE-bench coverage of the GA build.",
    },
    {
        "canonical_slug": "openai/gpt-5.6-cyber",
        "reason": "Only the Advanced Cybersecurity Completion Rate is printed. ExploitGym "
                  "and ExploitBench results appear as prose comparisons without values.",
        "revisit": "Ingest the promised GPT-5.6-Cyber system card when published.",
    },
)


def _upsert_benchmark_catalog(conn: sqlite3.Connection) -> int:
    inserted = 0
    for bid, (name, category, metric_default, hib, source_url) in BENCHMARK_CATALOG.items():
        cur = conn.execute(
            """INSERT OR IGNORE INTO benchmark
                 (id, name, category, metric_default, higher_is_better, source_url)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (bid, name, category, metric_default, hib, source_url),
        )
        inserted += cur.rowcount or 0
    return inserted


def _snapshot(conn: sqlite3.Connection, entry: dict, now: str) -> tuple[int, bool]:
    """Content-hashed snapshot for one launch benchmark set."""
    payload = json.dumps(entry, sort_keys=True, default=str).encode()
    digest = hashlib.sha256(payload).hexdigest()
    source_id = entry["source_id"]
    url = entry["url"]

    row = conn.execute(
        "SELECT id FROM source_snapshot WHERE source_id=? AND url=? AND content_hash=?",
        (source_id, url, digest),
    ).fetchone()
    if row:
        return int(row[0]), False

    raw_dir = REPO_ROOT / "data" / "raw" / source_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{entry['set_id']}_{digest[:8]}.json"
    raw_path.write_bytes(payload)

    cur = conn.execute(
        """INSERT INTO source_snapshot
             (source_id, url, fetched_at, content_hash, parser_version, raw_path)
           VALUES (?, ?, ?, ?, 'launch-benchmarks-0.1', ?)""",
        (source_id, url, now, digest, str(raw_path.relative_to(REPO_ROOT))),
    )
    snap_id = cur.lastrowid
    if snap_id is None:  # pragma: no cover - sqlite always sets it for INSERT
        raise RuntimeError(f"source_snapshot insert returned no rowid for {url}")
    return int(snap_id), True


def _model_ids(conn: sqlite3.Connection, entry: dict) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for col in entry["columns"]:
        slug = col.get("model_slug")
        if not slug or slug in out:
            continue
        row = conn.execute("SELECT id FROM model WHERE canonical_slug=?", (slug,)).fetchone()
        out[slug] = int(row[0]) if row else None
    return out


def promote_launch_benchmarks(conn: sqlite3.Connection) -> dict[str, int]:
    """Write vendor-published launch eval tables as self-reported benchmark facts."""
    now = utcnow()
    benchmarks_added = _upsert_benchmark_catalog(conn)
    snapshots_created = inserted = skipped_cells = unresolved = 0

    for entry in LAUNCH_BENCHMARK_SETS:
        snap, created = _snapshot(conn, entry, now)
        snapshots_created += int(created)
        conn.execute("DELETE FROM benchmark_result WHERE source_snapshot_id=?", (snap,))

        ids = _model_ids(conn, entry)
        base_condition = entry.get("row_condition", {})
        measured_at = entry["published_at"]

        for bench_id, printed_label, metric, values, row_condition in entry["rows"]:
            if len(values) != len(entry["columns"]):
                raise ValueError(
                    f"{entry['set_id']}: row {printed_label!r} has {len(values)} values "
                    f"for {len(entry['columns'])} columns"
                )
            for col, value in zip(entry["columns"], values):
                slug = col.get("model_slug")
                if not slug or value is None:
                    skipped_cells += 1
                    continue
                model_id = ids.get(slug)
                if model_id is None:
                    unresolved += 1
                    continue
                condition = {**base_condition, **row_condition, **col.get("condition", {})}
                conn.execute(
                    """INSERT INTO benchmark_result
                         (model_id, benchmark_id, score, metric, eval_condition_json,
                          self_reported, measured_at, source_snapshot_id, raw_record_json)
                       VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                    (model_id, bench_id, float(value), metric,
                     json.dumps(condition, sort_keys=True) if condition else None,
                     measured_at, snap,
                     json.dumps({"set_id": entry["set_id"],
                                 "printed_benchmark": printed_label,
                                 "printed_column": col["label"],
                                 "printed_value": value,
                                 "source_url": entry["url"],
                                 "table_notes": entry.get("table_notes", ())},
                                sort_keys=True)),
                )
                inserted += 1

    conn.commit()
    return {
        "sets": len(LAUNCH_BENCHMARK_SETS),
        "benchmarks_added": benchmarks_added,
        "snapshots_created": snapshots_created,
        "results_inserted": inserted,
        "comparison_or_blank_cells": skipped_cells,
        "unresolved_models": unresolved,
        "known_gaps": len(KNOWN_BENCHMARK_GAPS),
    }


if __name__ == "__main__":
    from ingest.base import connect

    with connect() as c:
        print(json.dumps(promote_launch_benchmarks(c), indent=2))
