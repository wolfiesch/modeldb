"""Curated launch-window identity for releases no first-party catalog lists yet.

`store.spine.build_spine` mints canonical identity only from first-party
models.dev namespaces. That gate keeps re-export spellings out of the spine, but
it also means a flagship release stays invisible for days or weeks while only
aggregators (OpenRouter, Vercel, Kilo, Chutes, Fireworks) carry it - and models
that never enter a token-API catalog at all (limited-access pilots, pure
open-weight drops) would never appear.

This module closes that window the way the new-model-drop rule prescribes: add
the model now with explicit provenance and confidence, then let the normal
promotion path enrich it as snapshots arrive. Each entry:

  1. persists its textually-confirmed facts as a `provider_blog` snapshot,
  2. mints the canonical `model` row when missing (idempotent on canonical_slug),
  3. attaches the aliases every downstream promoter matches on - provider ids,
     bare names, display names, Hugging Face repo ids.

Benchmark NUMBERS quoted in an announcement stay inside the evidence payload.
They are self-reported and frequently image-only, so they never become
`benchmark_result` rows here; independent aggregators supply those with their own
provenance.

An entry stays only until a first-party catalog covers the release. Once
models.dev lists it, `build_spine` dedupes on `canonical_slug` and the entry
becomes a no-op that only keeps the announcement evidence attached.

Usage:
    python -m store.launch_registry
"""
from __future__ import annotations

import sqlite3
from typing import Any

from ingest.base import connect, utcnow
from resolve.normalize import normalize_alias
from store.announcement import capture_announcement
from store.spine import _ensure_org, _write_alias

# Each entry: identity for the `model` row, `aliases` for resolution, and
# `evidence` for the provider_blog snapshot. `evidence` must carry `source_url`.
LAUNCH_ENTRIES: tuple[dict[str, Any], ...] = (
    {
        "canonical_slug": "anthropic/claude-sonnet-5",
        "display_name": "Claude Sonnet 5",
        "developer_id": "anthropic",
        "family": "claude-sonnet",
        "generation": "5",
        "tier_or_variant": "sonnet",
        "training_role": "reasoning",
        "release_date": "2026-06-30",
        "open_weights": False,
        "confidence": "verified",
        "aliases": (
            ("claude-sonnet-5", "bare_name"),
            ("anthropic/claude-sonnet-5", "api_model_id"),
        ),
        "evidence": {
            "source_url": "https://www.anthropic.com/news/claude-sonnet-5",
            "release_date": "2026-06-30",
            "positioning": "most agentic Sonnet yet; performance close to Opus 4.8 at "
                           "lower price; improvement over Sonnet 4.6 on "
                           "reasoning/tool-use/coding.",
            "pricing_intro": {"input_per_1m": 2, "output_per_1m": 10,
                              "through": "2026-08-31"},
            "pricing_standard": {"input_per_1m": 3, "output_per_1m": 15},
            "tokenizer_change": "updated tokenizer; same input maps to ~1.0-1.35x more "
                                "tokens vs Sonnet 4.6.",
            "named_benchmarks_image_only": ["BrowseComp", "OSWorld-Verified",
                                            "Humanity's Last Exam (HLE)"],
            "benchmark_numbers": "NOT captured: reported only as chart images. Await the "
                                 "Sonnet 5 System Card PDF or independent aggregators.",
            "system_card_url": "https://www.anthropic.com/claude-sonnet-5-system-card",
            "cyber_safeguards": "enabled by default (Cyber Verification Program).",
        },
    },
    {
        "canonical_slug": "deepseek/deepseek-v4-flash-0731",
        "display_name": "DeepSeek V4 Flash 0731",
        "developer_id": "deepseek",
        "family": "deepseek-v4",
        "generation": "4",
        "tier_or_variant": "flash",
        "training_role": "reasoning",
        "release_date": "2026-07-31",
        "snapshot_date": "2026-07-31",
        "stability": "pinned",
        "open_weights": True,
        "confidence": "verified",
        "aliases": (
            ("deepseek/deepseek-v4-flash-0731", "api_model_id"),
            ("deepseek-v4-flash-0731", "bare_name"),
            ("DeepSeek-V4-Flash-0731", "display_name"),
            ("deepseek-ai/DeepSeek-V4-Flash-0731", "hf_repo_id"),
            ("~deepseek/deepseek-v4-flash-latest", "latest_alias"),
        ),
        "evidence": {
            "source_url": "https://api-docs.deepseek.com/updates/",
            "release_date": "2026-07-31",
            "status": "public beta; official release of DeepSeek-V4-Flash, superseding "
                      "DeepSeek-V4-Flash-Preview.",
            "architecture": "same architecture and size as V4-Flash-Preview; gains come "
                            "from re-post-training, not a larger network.",
            "context": {"input_tokens": 1_048_576, "max_output_tokens": 384_000},
            "pricing_per_1m": {"input_cache_miss": 0.14, "input_cache_hit": 0.0028,
                               "output": 0.28},
            "peak_pricing_policy": "announced: 2x during Beijing 09:00-12:00 and "
                                   "14:00-18:00.",
            "api_surfaces": ["OpenAI ChatCompletions", "OpenAI Responses",
                             "Anthropic messages"],
            "legacy_mapping": "deepseek-chat / deepseek-reasoner map to the non-thinking "
                              "and thinking modes of deepseek-v4-flash and retire three "
                              "months after 2026-07-31.",
            "weights": "MIT-licensed weights at deepseek-ai/DeepSeek-V4-Flash-0731.",
            "pricing_docs_url": "https://api-docs.deepseek.com/quick_start/pricing/",
        },
    },
    {
        "canonical_slug": "anthropic/claude-opus-5-fast",
        "display_name": "Claude Opus 5 Fast",
        "developer_id": "anthropic",
        "family": "claude-opus",
        "generation": "5",
        "tier_or_variant": "opus-fast",
        "training_role": "reasoning",
        "release_date": "2026-07-24",
        "knowledge_cutoff": "2026-05",
        "stability": "preview",
        "open_weights": False,
        "confidence": "verified",
        "aliases": (
            ("anthropic/claude-opus-5-fast", "api_model_id"),
            ("claude-opus-5-fast", "bare_name"),
            ("Claude Opus 5 Fast", "display_name"),
        ),
        "evidence": {
            "source_url": "https://platform.claude.com/docs/en/build-with-claude/fast-mode",
            "release_date": "2026-07-24",
            "identity_note": "serving-speed tier of claude-opus-5, priced and throttled "
                             "separately, so it gets its own canonical row (same "
                             "treatment as MiniMax-M2.5-highspeed). This is NOT a "
                             "reasoning-effort variant; effort belongs in "
                             "benchmark_result.eval_condition_json.",
            "activation": "speed=\"fast\" with the fast-mode-2026-02-01 beta header.",
            "supported_models": ["claude-opus-5", "claude-opus-4-8"],
            "availability": "research preview, first-party Claude API only; not on "
                            "Amazon Bedrock, Google Cloud, or Microsoft Foundry; access "
                            "via account manager or waitlist.",
            "pricing_per_1m": {"input": 10, "output": 50},
            "standard_opus_5_pricing_per_1m": {"input": 5, "output": 25},
            "behavior": "raises output tokens per second, not time to first token; not "
                        "available on the Batch API; switching speeds invalidates "
                        "prompt caching.",
        },
    },
    {
        # models.dev renames this developer's ids to `thinkingmachines/<repo>`, so the
        # sibling row is `thinkingmachines/thinkingmachines/Inkling`. Matching that
        # spelling keeps build_spine from minting a second row for this release.
        "canonical_slug": "thinkingmachines/thinkingmachines/Inkling-Small",
        "display_name": "Inkling-Small",
        "developer_id": "thinkingmachines",
        "family": "inkling",
        "tier_or_variant": "small",
        "parameter_scale": "276b-a12b",
        "training_role": "reasoning",
        "release_date": "2026-07-30",
        "open_weights": True,
        "confidence": "verified",
        "aliases": (
            ("thinkingmachines/Inkling-Small", "api_model_id"),
            ("Inkling-Small", "bare_name"),
            ("Thinking Machines: Inkling Small", "display_name"),
            ("thinkingmachines/Inkling-Small", "hf_repo_id"),
        ),
        "evidence": {
            "source_url": "https://thinkingmachines.ai/news/inkling-small/",
            "release_date": "2026-07-30",
            "architecture": "Mixture-of-Experts, 276B total parameters with 12B active; "
                            "about one quarter the size of Inkling (975B total, 41B "
                            "active).",
            "context_tokens": 1_000_000,
            "modalities": "text, image, and audio input; text output; native reasoning "
                          "over audio and images; adjustable thinking effort.",
            "training_hardware": "NVIDIA GB300 NVL72.",
            "weights": "full weights released (Apache-2.0) at "
                       "thinkingmachines/Inkling-Small; HF repo created 2026-07-27.",
            "surfaces": "fine-tuning on Tinker; chat in Tinker Playground.",
            "model_card_url": "https://thinkingmachines.ai/model-card/inkling-small/",
            "benchmark_numbers": "NOT captured here; Artificial Analysis places it "
                                 "within a point of Inkling on their intelligence index.",
        },
    },
    {
        "canonical_slug": "minimax/MiniMax-H3",
        "display_name": "MiniMax-H3",
        "developer_id": "minimax",
        "family": "minimax-h",
        "generation": "3",
        "release_date": "2026-07-31",
        "open_weights": False,
        "confidence": "verified",
        "aliases": (
            ("MiniMax-H3", "api_model_id"),
            ("minimax/minimax-h3", "api_model_id"),
            ("minimax-h3", "bare_name"),
            ("MiniMaxAI/MiniMax-H3", "hf_repo_id"),
        ),
        "evidence": {
            "source_url": "https://www.minimax.io/blog/minimax-h3",
            "release_date": "2026-07-31",
            "class": "omni-modal generation model: text, image, video, and audio input; "
                     "generates video with native stereo audio.",
            "output_limits": "up to 2K resolution, up to 15 seconds per generation; 2K "
                             "is the default.",
            "technologies": ["Contextual Omni Representation", "H3-VAE",
                             "H3-Omni Transformer", "In-Context Regeneration"],
            "pricing_per_second": {"2k_cny": 0.80, "768p_cny": 0.50},
            "api": "POST /v2/video_generation with model MiniMax-H3; Vercel AI Gateway "
                   "id minimax/minimax-h3.",
            "open_weights_status": "announced for release 'in the coming days' subject "
                                   "to regulation; MiniMaxAI/MiniMax-H3 repo created "
                                   "2026-07-28 with no published weights at capture "
                                   "time, so open_weights stays 0 until artifacts land.",
        },
    },
    {
        "canonical_slug": "alibaba/qwen3.8-max",
        "display_name": "Qwen3.8-Max",
        "developer_id": "alibaba",
        "family": "qwen",
        "generation": "3.8",
        "tier_or_variant": "max",
        "parameter_scale": "2.4t",
        "training_role": "reasoning",
        "release_date": "2026-08-03",
        "open_weights": False,
        "confidence": "probable",
        "aliases": (
            ("qwen3.8-max", "bare_name"),
            ("alibaba/qwen3.8-max", "api_model_id"),
            ("Qwen3.8-Max", "display_name"),
        ),
        "evidence": {
            "source_url": "https://www.alibabacloud.com/help/en/model-studio/models",
            "release_date": "2026-08-03",
            "availability": "general access through Alibaba Cloud Model Studio APIs and "
                            "QwenWork; preview (qwen3.8-max-preview) announced "
                            "2026-07-19 at WAIC Shanghai through Token Plan, Qoder, and "
                            "QoderWork.",
            "parameters": "2.4T total parameters (sparse MoE); active parameter count "
                          "not disclosed.",
            "context": "up to 1M tokens; the preview surface reports 983,616 input and "
                       "131,072 max output tokens.",
            "modalities": "text, image, video, and document input; text output.",
            "reasoning": "always-on reasoning with low/high/xhigh levels, default xhigh.",
            "open_weights_status": "Alibaba states weights will be released; not "
                                   "published at capture time, so open_weights stays 0.",
            "confidence_note": "release_date is the general-availability date; Alibaba "
                               "had not published a dated first-party launch post at "
                               "capture time, hence canonical_confidence=probable.",
            "vendor_claims": "second only to Claude Fable 5 in Alibaba's own comparison; "
                             "5th in Text Arena and 2nd in Vision Arena per Alibaba. "
                             "Self-reported, NOT captured as benchmark_result rows.",
        },
    },
    {
        "canonical_slug": "kwaipilot/kat-coder-pro-v2.5",
        "display_name": "KAT-Coder-Pro V2.5",
        "developer_id": "kwaipilot",
        "family": "kat-coder",
        "generation": "2.5",
        "tier_or_variant": "pro",
        "training_role": "reasoning",
        "release_date": "2026-07-10",
        "snapshot_date": "2026-07-10",
        "open_weights": False,
        "confidence": "verified",
        "aliases": (
            ("kwaipilot/kat-coder-pro-v2.5", "api_model_id"),
            ("kat-coder-pro-v2.5", "bare_name"),
            ("kat-coder-pro-v2.5-20260710", "dated_api_model_id"),
            ("Kwaipilot: KAT-Coder-Pro V2.5", "display_name"),
        ),
        "evidence": {
            "source_url": "https://arxiv.org/abs/2607.05471",
            "release_date": "2026-07-10",
            "developer": "KwaiKAT team (Kuaishou); served through StreamLake.",
            "class": "agentic coding model trained to operate inside executable "
                     "repositories rather than single-turn code generation.",
            "context_tokens": 256_000,
            "pricing_per_1m": {"input": 0.74, "output": 2.96, "input_cache_read": 0.15},
            "training_system": "AutoBuilder raised verifiable environments from 16.5% to "
                               "57.2% across 12 languages (100,000+ environments); "
                               "sandbox hardening cut RL trajectory feedback errors from "
                               "~16% to under 2%; asymmetric actor-critic PPO with "
                               "hindsight-augmented value estimation; Multi-Teacher "
                               "On-Policy Distillation over five domain experts.",
            "self_reported_benchmarks": "PinchBench 94.9 (top agentic tool-use) and "
                                        "SWE-Bench Pro 65.2 (second behind Opus 4.8), "
                                        "under a Claude Code harness. NOT captured as "
                                        "benchmark_result rows: self-reported.",
        },
    },
    {
        "canonical_slug": "kwaipilot/kat-coder-air-v2.5",
        "display_name": "KAT-Coder-Air V2.5",
        "developer_id": "kwaipilot",
        "family": "kat-coder",
        "generation": "2.5",
        "tier_or_variant": "air",
        "training_role": "reasoning",
        "release_date": "2026-07-10",
        "snapshot_date": "2026-07-10",
        "open_weights": False,
        "confidence": "verified",
        "aliases": (
            ("kwaipilot/kat-coder-air-v2.5", "api_model_id"),
            ("kat-coder-air-v2.5", "bare_name"),
            ("Kwaipilot: KAT-Coder-Air V2.5", "display_name"),
        ),
        "evidence": {
            "source_url": "https://arxiv.org/abs/2607.05471",
            "release_date": "2026-07-10",
            "developer": "KwaiKAT team (Kuaishou); served through StreamLake.",
            "class": "smaller-cost agentic coding tier of the KAT-Coder V2.5 release.",
            "context_tokens": 256_000,
            "pricing_per_1m": {"input": 0.15, "output": 0.60, "input_cache_read": 0.03},
        },
    },
    {
        "canonical_slug": "kwaipilot/KAT-Coder-V2.5-Dev",
        "display_name": "KAT-Coder-V2.5-Dev",
        "developer_id": "kwaipilot",
        "family": "kat-coder",
        "generation": "2.5",
        "tier_or_variant": "dev",
        "parameter_scale": "35b-a3b",
        "training_role": "instruct",
        "release_date": "2026-07-23",
        "open_weights": True,
        "confidence": "verified",
        "aliases": (
            ("Kwaipilot/KAT-Coder-V2.5-Dev", "hf_repo_id"),
            ("KAT-Coder-V2.5-Dev", "bare_name"),
        ),
        "evidence": {
            "source_url": "https://huggingface.co/Kwaipilot/KAT-Coder-V2.5-Dev",
            "release_date": "2026-07-23",
            "class": "open-weight companion to the served KAT-Coder V2.5 tiers.",
            "architecture": "35B total / 3B active MoE post-trained from "
                            "Qwen3.6-35B-A3B; text only, no vision.",
            "training": "127K SFT examples plus reinforcement learning.",
            "license": "apache-2.0",
            "note": "distinct from the served kat-coder-pro/air v2.5 tiers: different "
                    "parameter scale and base model, so it is its own canonical row.",
        },
    },
    {
        "canonical_slug": "xai/grok-voice-think-fast-2.0",
        "display_name": "Grok Voice Think Fast 2.0",
        "developer_id": "xai",
        "family": "grok-voice",
        "generation": "2.0",
        "tier_or_variant": "think-fast",
        "release_date": "2026-07-29",
        "open_weights": False,
        "confidence": "verified",
        "aliases": (
            ("xai/grok-voice-think-fast-2.0", "api_model_id"),
            ("grok-voice-think-fast-2.0", "bare_name"),
            ("Grok Voice Think Fast 2.0", "display_name"),
        ),
        "evidence": {
            "source_url": "https://x.ai/news/grok-voice-think-fast-2",
            "release_date": "2026-07-29",
            "class": "speech-to-speech voice model over a realtime WebSocket "
                     "(wss://api.x.ai/v1/realtime).",
            "pricing_per_audio_minute": 0.08,
            "latest_alias_migration": "grok-voice-latest moves from "
                                      "grok-voice-think-fast-1.0 to 2.0 on 2026-08-05; "
                                      "pin 1.0 to stay.",
            "vendor_claims": "1.5-2.0x transcription accuracy over large STT models and "
                             "a ~10x gap in noisy or telephony audio; faster, more "
                             "token-efficient reasoning with earlier tool calls. "
                             "Self-reported, NOT captured as benchmark_result rows.",
            "docs_url": "https://docs.x.ai/developers/model-capabilities/audio/speech-to-speech",
        },
    },
    {
        "canonical_slug": "google/gemini-3.5-flash-cyber",
        "display_name": "Gemini 3.5 Flash Cyber",
        "developer_id": "google",
        "family": "gemini",
        "generation": "3.5",
        "tier_or_variant": "flash-cyber",
        "training_role": "reasoning",
        "release_date": "2026-07-21",
        "stability": "preview",
        "open_weights": False,
        "confidence": "verified",
        "aliases": (
            ("gemini-3.5-flash-cyber", "bare_name"),
            ("google/gemini-3.5-flash-cyber", "api_model_id"),
            ("Gemini 3.5 Flash Cyber", "display_name"),
        ),
        "evidence": {
            "source_url": "https://deepmind.google/blog/introducing-gemini-3-5-flash-cyber/",
            "release_date": "2026-07-21",
            "class": "cybersecurity-specialized fine-tune of Gemini 3.5 Flash for "
                     "finding, validating, and patching vulnerabilities.",
            "availability": "limited-access pilot inside CodeMender for governments and "
                            "trusted partners; no public token pricing, hence "
                            "stability=preview and no price rows.",
            "usage_pattern": "multiple agents invoked over a large codebase collaborate "
                             "on one vulnerability report.",
            "vendor_claims": "competitive with larger models on CyberGym; exceeds "
                             "mainline 3.5 Flash and 3.6 Flash under stressed "
                             "evaluation; more unique vulnerabilities on complex targets "
                             "such as V8. Self-reported, NOT captured as "
                             "benchmark_result rows.",
            "launch_post_url": "https://blog.google/innovation-and-ai/models-and-research/"
                               "gemini-models/gemini-3-6-flash-3-5-flash-lite-3-5-flash-cyber/",
        },
    },
    {
        "canonical_slug": "lgai/K-EXAONE-2.0-750B-A37B",
        "display_name": "K-EXAONE 2.0",
        "developer_id": "lgai",
        "family": "k-exaone",
        "generation": "2.0",
        "parameter_scale": "750b-a37b",
        "training_role": "reasoning",
        "release_date": "2026-07-31",
        "knowledge_cutoff": "2025-Q2",
        "open_weights": True,
        "confidence": "verified",
        "aliases": (
            ("LGAI-EXAONE/K-EXAONE-2.0-750B-A37B", "hf_repo_id"),
            ("K-EXAONE-2.0-750B-A37B", "bare_name"),
            ("K-EXAONE 2.0", "display_name"),
        ),
        "evidence": {
            "source_url": "https://www.lgresearch.ai/news/view?seq=678",
            "release_date": "2026-07-31",
            "developer": "LG AI Research; part of Korea's Sovereign AI Foundation Model "
                         "Project.",
            "architecture": "MoE, 750B total with 37B active; 1 shared expert plus 256 "
                            "routed experts with 8 activated; 78 layers (2 dense, 76 "
                            "sparse); hidden 6,144; intermediate 18,432; 64 query and 8 "
                            "key/value heads; vocabulary 153,600.",
            "context_tokens": 262_144,
            "license": "apache-2.0",
            "languages": "expanded from 6 to 10: Korean, English, Spanish, German, "
                         "Japanese, Vietnamese, French, Italian, Polish, Portuguese.",
            "training": "upcycled from the 236B first-phase model with continual "
                        "pretraining, difficulty-focused mid-training, and post-training.",
            "published_artifacts": "base plus FP8, NVFP4, and DSpark quantized repos; "
                                   "base HF repo created 2026-07-29.",
            "vendor_claims": "average 70.1/100 across 24 benchmarks; emphasis on "
                             "long-context retrieval and safety. Self-reported, NOT "
                             "captured as benchmark_result rows.",
        },
    },
    {
        "canonical_slug": "amd/Instella-MoE-16B-A3B",
        "display_name": "Instella-MoE-16B-A3B",
        "developer_id": "amd",
        "family": "instella",
        "generation": "moe",
        "parameter_scale": "16b-a2.8b",
        "training_role": "reasoning",
        "release_date": "2026-07-23",
        "open_weights": True,
        "confidence": "verified",
        "aliases": (
            ("amd/Instella-MoE-16B-A3B-Think", "hf_repo_id"),
            ("amd/Instella-MoE-16B-A3B-Base", "hf_repo_id"),
            ("Instella-MoE-16B-A3B", "bare_name"),
            ("Instella-MoE-16B-A3B-Think", "display_name"),
        ),
        "evidence": {
            "source_url": "https://rocm.blogs.amd.com/artificial-intelligence/instella-moe/README.html",
            "release_date": "2026-07-23",
            "class": "fully open Mixture-of-Experts language model: weights for every "
                     "training stage, training configs, data mixtures, and code.",
            "architecture": "16B total parameters with 2.8B active per token; 27 decoder "
                            "layers; hidden 2,048; 16 attention heads; 64 experts (2 "
                            "shared, 6 active); vocabulary 128,896; Gated Multi-head "
                            "Latent Attention and FarSkip-Collective connectivity.",
            "training_hardware": "trained from scratch on AMD Instinct MI300X and MI325X "
                                 "with the ROCm stack (Primus and Miles frameworks).",
            "checkpoints": "Pretrain, Midtrain, Base (long context), SFT, DPO, RL, and "
                           "Think; flagship instruct checkpoint is "
                           "Instella-MoE-16B-A3B-Think, HF repos created 2026-07-23.",
            "code_url": "https://github.com/AMD-AGI/Instella-MoE",
        },
    },
)

_MODEL_COLUMNS = (
    "canonical_slug", "developer_id", "family", "generation", "tier_or_variant",
    "parameter_scale", "training_role", "release_date", "snapshot_date",
    "knowledge_cutoff", "stability", "open_weights", "canonical_confidence",
    "display_name",
)


def _model_values(entry: dict[str, Any]) -> tuple[Any, ...]:
    open_weights = entry.get("open_weights")
    return (
        entry["canonical_slug"],
        entry["developer_id"],
        entry.get("family"),
        entry.get("generation"),
        entry.get("tier_or_variant"),
        entry.get("parameter_scale"),
        entry.get("training_role"),
        entry.get("release_date"),
        entry.get("snapshot_date", entry.get("release_date")),
        entry.get("knowledge_cutoff"),
        entry.get("stability"),
        None if open_weights is None else int(bool(open_weights)),
        entry.get("confidence", "probable"),
        entry["display_name"],
    )


def _mint(conn: sqlite3.Connection, entry: dict[str, Any], now: str) -> tuple[int, bool]:
    """Return (model_id, created). Idempotent on canonical_slug."""
    slug = entry["canonical_slug"]
    row = conn.execute("SELECT id FROM model WHERE canonical_slug = ?", (slug,)).fetchone()
    if row:
        return int(row[0]), False

    _ensure_org(conn, entry["developer_id"], entry["developer_id"])
    placeholders = ",".join("?" * (len(_MODEL_COLUMNS) + 2))
    cur = conn.execute(
        f"INSERT INTO model ({','.join(_MODEL_COLUMNS)}, created_at, updated_at) "
        f"VALUES ({placeholders})",
        (*_model_values(entry), now, now),
    )
    model_id = cur.lastrowid
    assert model_id is not None  # sqlite3 sets lastrowid after a single-row INSERT
    return int(model_id), True


def promote_launch_registry(conn: sqlite3.Connection) -> dict[str, int]:
    """Mint curated launch-window models and attach their announcement evidence."""
    now = utcnow()
    models_created = 0
    aliases_created = 0
    snapshots_created = 0

    for entry in LAUNCH_ENTRIES:
        model_id, created = _mint(conn, entry, now)
        models_created += int(created)

        for alias_string, alias_kind in entry["aliases"]:
            aliases_created += _write_alias(
                conn, source_id="provider_blog", alias_string=alias_string,
                alias_normalized=normalize_alias(alias_string), alias_kind=alias_kind,
                model_id=model_id, method="exact_provider_doc", confidence=1.0, now=now,
            )

        evidence = {
            **entry["evidence"],
            "canonical_slug": entry["canonical_slug"],
            "display_name": entry["display_name"],
        }
        snapshots_created += int(capture_announcement(conn, evidence)["created"])

    conn.commit()
    return {
        "entries": len(LAUNCH_ENTRIES),
        "models_created": models_created,
        "aliases_created": aliases_created,
        "snapshots_created": snapshots_created,
    }


if __name__ == "__main__":
    with connect() as c:
        print(promote_launch_registry(c))
