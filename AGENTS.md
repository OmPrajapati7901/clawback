# Clawback — project brief

## What it is

A web app that checks supplier bills (invoices) against supplier contracts before a company pays them.
It catches overcharges: prices raised more than the contract allows, missed bulk discounts,
and fees for things the contract says are included. It quotes the exact contract clause as proof
and drafts a polite dispute email.

## Context

Built solo in 5 hours at the MONEY TALKS 2 hackathon (Money Operations track).
Requirements: all LLM calls go through the Nicrron API; every agent step is traced to PRISM by Block Convey.
All data is synthetic (fictional companies, fake invoices). Never use real financial data.

## The demo goal

Upload an invoice → watch the agent's steps live → see "Overbilled $4,180, clause 7.2" with the clause
highlighted and a dispute email drafted. A working product, not a mockup.

## Rules

- CONTRACT.md is the source of truth for data formats, pricing rules and the API. Read it first.
  Never edit it; if something in it seems wrong, stop and tell me.
- The LLM handles language (reading contracts, explanations, emails). Plain Python handles all money math.
- Keep it simple: no login, no extra frameworks, no features beyond what I ask for.
- You own: backend/   ← (in AGENTS.md change this to: frontend/, data/, eval/, tests/, Dockerfile, README.md)
- Never edit files outside the folders you own.

## PRISM tracing (do not remove)

This project sends traces to PRISM. Env vars: `PRISMTRACE_API_KEY`,
`PRISMTRACE_PROJECT_ID`, `PRISMTRACE_HOST`.

Tracing is currently wired at: none yet (repository was empty; `.env.example` only)

**Standing rule.** Whenever you add or change an agent, chain, graph, tool,
retriever, or any entry point that calls a model, wire it to PRISM before you
finish. Unwired code is invisible in the dashboard. If you are unsure whether
something is covered, assume it is not and wire it.
