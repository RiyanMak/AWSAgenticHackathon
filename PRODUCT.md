# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

- App: Shiny for Python (confirmed 2026-10-23). Themes must be buildable with Shiny's CSS and theming.
- Presentation: Quarto reveal.js deck in `presentation/`.
- Agents: Amazon Bedrock, AgentCore and Strands Agents (see `docs/ARCHITECTURE.md`).

## Users

Primary: a patient at home who has just received reports from a provider (labs, an imaging report, a history summary) through a patient portal. They read on a phone or a laptop, often anxious, often in the evening, and the reports were written for other clinicians, not for them. Their job: understand what the reports say, what is urgent and what is not, and what to do next.

Secondary audience for the hackathon only: judges at the AWS Austin Agentic AI Hackathon (Track 1, Caregivers), watching the deck and a recorded demo.

## Product Purpose

CareRelay lets the patient upload those reports and get them back in plain language, with every finding given an owner and a next step: what it means, whether it was expected given their history, what they can do while waiting, and an in-network follow-up they can confirm. Success: the patient knows what each finding means and has a concrete, affordable next step, and no incidental finding is left without one.

## Positioning

A team of specialist agents (Lab, Radiology, History, Summarize, Wellness, Next Steps, Insurance) that separates findings explained by the patient's own history from truly incidental ones, keeps an incidental ledger so nothing is dropped, and books against the patient's actual plan, network and deductible. Deterministic tools do the math (reference ranges, network, cost); the model explains.

## Operating Context

- Inputs: lab PDF, imaging report PDF (or X-ray), medical history document (PCP health summary or patient questionnaire), insurance card or coverage.
- Outputs: plain-language summary, incidental ledger, wellness options while waiting, proposed in-network appointments that a human confirms.
- Demo flow: three beats (upload, merge and wait, follow up) on synthetic case_001.

## Capabilities and Constraints

- Prototype only: synthetic or public data, not a clinical system, not medical advice. Red flags always require human confirmation; appointments stay "proposed" until confirmed.
- Undecided: number of agents in the final build, eval results, which hosting surface is demoed.

## Brand Commitments

- Name: CareRelay (fixed). No logo, colours or AWS branding required.

## Evidence on Hand

- 10 synthetic cases with answer keys, rendered PDFs and FHIR ground truth in `data/` (see `data/CASES.md`); case_001 is the hero case.
- Mock plans, provider network and cost tools in `data/network/` and `data/network.py`.
- None yet: real users, testimonials, usage metrics, eval numbers. Do not fabricate them.

## Product Principles

1. The patient's question comes first: "what does this mean and what do I do?", answered before any detail.
2. Every finding gets an owner and a next step; incidental findings are never silently dropped.
3. Calm, not alarming; urgent things are unmistakable without making everything feel urgent.
4. Honest about uncertainty and about being a prototype; the model explains, rules decide.
5. Real costs and real network, not generic advice.
