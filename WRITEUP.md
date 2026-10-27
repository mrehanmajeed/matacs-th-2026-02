# Write-up: AI-assisted proposal triage

AI reads each proposal and pulls out the facts, each backed by a quote. Plain rules check the must-haves, do the arithmetic and rank. People confirm facts, review the ranking and make the award, and every step is logged (see `diagram/process-flow.png`; `ranking.json` is produced by `prototype/triage.py`).

## 1. AI vs rules

- **AI (one step):** fact extraction. One call per proposal turns free text into a fixed list of facts (licence holder, insurance, installs, price, weeks, warranties, team items), each with a status (stated, not stated or unclear) and a word-for-word quote. Proposals phrase things in many ways; that is where AI helps.
- **Rules (everything else):** file hashing and duplicate check, text extraction/OCR and quality check, a keyword scan for hidden instructions, checking the AI output (format, quotes really in the document, sensible numbers, CAD), the pass/fail gates, scoring, status, tie-breaks and the one-line reasons (templates, not AI).
- **People:** the admin sets criteria; the reviewer uploads and works through three checkpoints.
- **Why the line is there:** gates, maths and ranking must be repeatable, explainable and auditable. An AI doing arithmetic or ranking can vary between runs, can't reliably show its working, and can be talked into things by the text it reads, which proposal C tries.

## 2. Consistency and explainability

- The AI step uses a pinned model, a versioned prompt (hash stored) and output forced into a JSON schema, re-checked in code. Current Claude models no longer allow temperature 0, so the design doesn't rely on it.
- Facts are cached by file hash, so ranking the same files twice reuses the same facts, and plain-code scoring gives an identical result.
- Honest caveat: a fresh re-extraction could read an ambiguous sentence differently, which is why facts are human-confirmed and stored, and ranking always uses them.
- Fixed tie-breaks: higher unrounded total, then experience score, then lower price, then proposal letter.
- **What the reviewer sees:** points per criterion, the formula (e.g. price points = lowest eligible price ÷ this price × 25) and the quote behind every fact. The one-line reason is built from the same numbers, so it can't claim anything the breakdown doesn't.

## 3. Human in the loop and audit

- **Checkpoint 1, fact review:** facts sit next to their quotes; the reviewer must confirm anything unverified, unclear or not stated. Edits need a reason.
- **Checkpoint 2, ranking review:** the reviewer resolves every flag (e.g. obtains D's schedule) and can override a status or rank, with a mandatory reason.
- **Checkpoint 3, award:** a person decides; the tool only recommends. The run then locks.
- **The audit log (append-only) records:** user and timestamp; file hashes; criteria version; model id and prompt version/hash; the raw AI output; the validated facts; every human edit or override with its reason; scores and reasons; and the final decision.

## 4. Changing criteria

- Every save creates a new, read-only criteria version; each run pins the version it started with.
- Existing scores keep their version and are marked "stale" when a newer one exists; nothing changes silently.
- Rescoring reruns only the cheap rule step on stored facts, with no AI call. If a new criterion needs a fact not yet extracted, only that field is re-extracted and confirmed at checkpoint 1.
- The reviewer sees the rank changes between versions.
- Once an award is recorded the run is locked.
- Changing criteria mid-review requires a reason and is logged.

## 5. Risks and safeguards

- **Wrong extraction** → every fact carries its quote, reviewed at checkpoint 1 before any score.
- **Made-up facts** → each quote must appear word for word in the document, or the fact is unverified and flagged; the AI must say "not stated" rather than guess.
- **Prompt injection or manipulation** → proposal text is marked as untrusted data, the AI never scores, and a separate rule scan looks for such text. C contains a note asking to be ranked first: it is flagged, the note has no effect, and C is scored on its facts only (provisional 77.1, would place 3rd).
- **Missing information treated as "no"** → "not stated" is its own status, never "false"; a missing requirement flags rather than rejects. D gives no completion time, so it is flagged with timeline scored 0, not dropped or guessed.
- **Price-led bias or skipped gates** → gates run first and ineligible bids are left out of the comparison pool. B is cheapest and fastest, but its licence belongs to a subcontractor to be confirmed after award, so it is ineligible and its price doesn't shift other scores.
- **Bias from company names or marketing** → scoring sees only facts, never names; marketing claims are listed as unsupported and score nothing; names can be hidden from reviewers until award.
- **Prices that aren't like-for-like** → price inclusions are extracted. A includes permits and utility connection; others don't say, so the reviewer confirms inclusions before award.
- **Experience outside the 5-year window** → C counts installs "since 2020", possibly including some before the window; such counts are marked unclear for the reviewer (accepted as 9 here, with a note).
- **Scanned or poor-quality PDFs** → OCR plus a text-quality check; near-empty text flags the file.
- **Model drift** → pinned model; any model or prompt change must first pass a regression test on a golden set of proposals with known facts.
- **Cost** → one AI call per unique file (hash cache), a small model, and no AI in scoring or rescoring.
- **Over-reliance on the tool** → a person always awards, and every flag needs a human decision with a reason.
