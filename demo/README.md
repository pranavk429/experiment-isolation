# Experiment Isolation — three-minute demo

This is the Track 3 lab demo. The product story is simple: **two experiments
share an audience; the dashboard proves it; one approval-gated cycle splits them
and proves the overlap is gone.**

Everything is local. No Flagsmith Cloud account, no production data.

## Before you record

```bash
cd "experiment-isolation"
bash lab/run.sh reset     # only if you want a clean collision again
bash lab/run.sh           # starts the lab, seeds drafts, audits, serves pages
```

Wait for the summary and open:

- http://localhost:8010 — self-hosted Flagsmith
- http://localhost:8020 — synthetic storefront
- http://localhost:8022 — overlap dashboard

## 0:00–0:30 — The collision

Open the dashboard (8022). Point at:

- **Audiences collide**, max Jaccard **100%**
- the pairwise matrix cell: shared 250 / union 250
- both experiment cards are **draft** and both target segment 1 (`us_mobile`)

Say: *"These are two legitimate draft experiments. Nothing in the flag UI tells
you they will enroll the same people. That is the contamination risk."*

## 0:30–1:00 — The audience is real

Open the storefront (8020). Evaluate `demo-us-mobile-001` with country US and
platform mobile. Show:

- both variants render (`urgent` banner, `short` tip)
- the request trace shows `POST /api/v1/identities/`
- the stable `flagsmith_experiment_bucket` trait (e.g. bucket 3)

Change country to GB or platform to desktop and show the flags fall back to
control. Say: *"This is synthetic traffic, but the evaluation path is the real
SDK/edge API, including the trait the fix depends on."*

Optionally show the raw JSON:

```bash
curl -s "http://localhost:8020/api/evaluate?identifier=demo-us-mobile-001&country=US&platform=mobile" | python3 -m json.tool
```

## 1:00–1:30 — The skill/engine measures it

Switch to the terminal. Show the engine audit is not hand-written:

```bash
source lab/.env
python3 -m engine.cli audit \
  --env "$LAB_DEV_ENV_KEY" --samples 500 --threshold 0.05 \
  --out lab/dashboard/audit.json
```

The compact summary says `jaccard=1.0`. The dashboard reloads the same file.
Say: *"The audit discovers non-completed experiments, samples identities, and
measures actual/projected enrollment. The dashboard is only a reader."*

## 1:30–2:20 — Fix it with approval

Run the whole local cycle:

```bash
bash lab/run.sh demo
```

Narrate the beats as they happen:

1. `plan` creates two bucket segments: `exp_iso_0_49` and `exp_iso_50_99`.
2. `apply` prints the approval token it verified, disables each rollout,
   swaps the audience, re-enables it, and starts the experiments.
3. `verify` samples 500 identities again: before 1.0 → after 0.0.
4. `receipt` writes the compact evidence file.

The command is explicit. The normal `bash lab/run.sh` path never applies
changes; `demo` is the opt-in local demonstration.

## 2:20–2:50 — The after state

Refresh the dashboard (8022). Point at:

- **Audiences isolated**, max Jaccard **0%**
- matrix labelled **before snapshot** (100%)
- **Before → after: 100% → 0%**, 100 points removed
- Evidence: `receipt.json` loaded, pass true, changes 4, token count, rollback

Say: *"The before matrix is preserved as evidence. The receipt is the compact
proof: same sample size, measured before and after, with rollback commands."*

## 2:50–3:00 — Close

Say: *"Self-hosted Flagsmith does the real work: experiments, segments,
multivariate flags, and the Postgres warehouse. The lab packages the whole loop
so another developer can run it with one command and see the collision before
they ship."*

## Reset for another take

```bash
bash lab/run.sh reset
bash lab/run.sh
```

## Fallback if the engine CLI is missing

The dashboard still loads an explicitly labelled **SAMPLE DATA** audit, with an
illustrative 100% → 0% panel. That is useful for UI work but is not evidence.
Do not present the sample as a measured run.
