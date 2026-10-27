# Write-up: AI-assisted proposal triage

AI reads each proposal and pulls out the facts, each backed by a quote. Simple rules check the must-haves, do the arithmetic and rank. People confirm facts, review the ranking and make the award. Key assumptions (5-year window counted from 2026, warranty split 50/50, progress reports aren't monitoring, missing facts score 0 and are flagged) are in README > Assumptions.

## 1. AI vs rules

- **AI (one step):** reading. One request per proposal turns the text into a fixed list of facts (licence holder, insurance, installs, price, weeks, warranties, team items), each marked stated, not stated or unclear, with a word-for-word quote. Proposals phrase things in many ways; that is where AI helps.
- **Rules (everything else):** duplicate-file check, getting text out of PDFs (text recognition for scans), a keyword scan for hidden instructions, checking the AI's answer (format, quotes really in the document, sensible numbers, no price in a foreign currency), gates, scoring, status, tie-breaks and the one-line reasons (templates, not AI).
- **People:** the admin sets criteria; the reviewer uploads files and works through three checkpoints.
- **Why there:** gates, maths and ranking must be repeatable, explainable and auditable. An AI doing them can vary between runs, can't reliably show its working, and can be talked round by the text it reads, which proposal C tries.

## 2. Consistency and explainability

- **Same files, same result.** Each uploaded file gets a fingerprint. The same file reuses its stored, human-checked facts instead of asking the AI again, and scoring is fixed arithmetic, so ranking twice gives exactly the same result.
- **Steady AI.** The AI version and prompt wording are fixed and recorded, and its answer must fit a fixed form that code re-checks. Temperature (how much the AI varies) is a setting, 0 for models that accept it; repeatability doesn't depend on it.
- **Honest caveat:** re-reading a file from scratch could interpret an ambiguous sentence differently, so ranking always uses the stored, person-confirmed facts.
- **Ties:** higher exact total, then experience score, then lower price, then letter.
- **Why a bid ranked there:** the reviewer sees points per criterion, how they were worked out (e.g. price points = lowest eligible price ÷ this price × 25) and the quote behind every fact. The reason line is built from the same numbers.

## 3. Human in the loop and audit

- **Checkpoint 1, fact review:** facts sit next to their quotes; the reviewer must confirm anything unverified, unclear or not stated. Edits need a reason.
- **Checkpoint 2, ranking review:** the reviewer resolves every flag (e.g. obtains D's schedule), which reruns the scoring rules, not the AI, and can override a status or rank with a mandatory reason.
- **Checkpoint 3, award:** a person decides; the tool only recommends. The run then locks.
- **The audit log records:** who and when; file fingerprints; criteria version; AI and prompt versions; the AI's raw answer; checked facts; every human edit or override with its reason; scores and reasons; the final decision. The prototype logs extraction and scoring runs; production would log every step.

## 4. Changing criteria

- Every save creates a new, read-only criteria version; each run is tied to its version, and scoring refuses facts confirmed under a different one.
- Existing scores keep their version and are marked "stale" when a newer one exists; nothing changes silently.
- Rescoring reruns only the rules on stored facts, with no AI. If a new criterion needs a new fact, only that fact is re-read and confirmed at checkpoint 1.
- The reviewer sees the rank changes between versions.
- Once an award is recorded the run is locked; mid-review criteria changes need a reason and are logged.

## 5. Risks and safeguards

- **Wrong extraction** → every fact carries its quote, reviewed at checkpoint 1 before scoring.
- **Made-up facts** → each quote must appear word for word in the document, or the fact is flagged unverified with the cause; the AI must say "not stated" rather than guess.
- **Failed extraction** → if the AI stops early or returns a broken answer, the bid is flagged "extraction failed" for a person, never silently dropped.
- **Prompt injection** → proposal text is marked untrusted, the AI never scores, and a separate rule scan looks for such text. C's note asking to be ranked first is flagged and has no effect; C is scored on its facts only (provisional 77.1, 3rd of 4 eligible bids; no official score until cleared).
- **Missing information treated as "no"** → "not stated" is its own status; a missing requirement flags rather than rejects. D gives no completion time, so it is flagged with timeline scored 0 (provisional 69.8, 4th of 4), not dropped.
- **Price-led bias or skipped gates** → gates run first and ineligible bids are left out of the comparison. B is the cheapest and fastest bid overall, but its licence belongs to a subcontractor to be confirmed after award, so it is ineligible and shifts no other score.
- **Bias from names or marketing** → scoring sees only facts; marketing claims are listed as unsupported and score nothing; names can be hidden until award.
- **Prices not like-for-like** → inclusions are recorded. A includes permits and utility connection; others don't say, so a review note asks for confirmation.
- **Experience outside the 5-year window** → C counts installs "since 2020"; its reason carries that caveat (accepted as 9 here).
- **Poor scans** → text recognition, and near-empty text flags the file.
- **AI behaviour drifting** → fixed AI version; re-test on sample proposals with known answers before any change.
- **Cost** → one AI request per unique file, a small low-cost model, no AI in scoring.
- **Over-reliance** → a person always awards, and every flag needs a human decision with a reason.
