# Security Testing Engine

`Security Testing Engine 8.0.0` is a Windows-first CompTIA Security+ SY0-701 study application built around question practice, adaptive review, progress tracking, and bank-quality validation.

It is designed to do two things well:

- help a learner move through a large question bank quickly
- quietly adapt behind the scenes so weak, fragile, confusing, or under-covered concepts come back at the right time

**What This Project Includes**

- A desktop Tkinter study app with `Smart Practice`, `Practice`, and `Exam` flows
- A cleaned default bank merged from multiple SY0-701-compatible sources
- Progress tracking, autosave, backup, restore, checkpoints, issue reporting, and analytics
- Import, validation, cleanup, benchmark, smoke-test, and quality-check tooling

**Included Content**

By default, the app now opens with the merged cleaned bank:

- `public_sy0701_bank_v4_plus_studyguide_clean.json`

That merged bank currently contains:

- `720` questions from the cleaned public SY0-701 bank
- `305` structured questions imported from the free study guide
- `152` verified screenshot imports from Chapter 1 through Chapter 4
- `53` verified screenshot imports from Chapter 5
- `1` quarantined screenshot review placeholder from Chapter 2
- `1231` total bank records

The screenshot coverage is complete for the local folders currently found in Downloads:

- Chapter 1 screenshot bank: `31` verified active records
- Chapter 2 screenshot bank: `31` records (`30` verified active, `1` still needs review because the source image contains no question content)
- Chapter 3 screenshot bank: `44` verified active records
- Chapter 4 screenshot bank: `47` verified active records
- Chapter 5 screenshot bank: `53` verified active records

Screenshot records that OCR could not safely turn into a real question are marked as suspended review items, so they stay out of normal practice until verified.

Related bank files in the repo:

- `public_sy0701_bank_v4.json`: original public source bank
- `public_sy0701_bank_v4_clean.json`: cleaned public bank
- `free_study_guide_a5_import_bank.json`: structured study-guide import
- `public_sy0701_bank_v4_plus_studyguide_clean.json`: merged default bank
- `chapter_screenshot_ocr_draft_bank.json`: screenshot OCR import records that were added to the default bank with source-review notes
- `chapter_screenshot_review_stubs_import_bank.json`: quarantined screenshot review placeholders for images that need transcription/verification

**Main Features**

- `Smart Practice`: adaptive mixed practice with follow-up logic and controlled bonus question insertion
- `Practice`: straightforward set-based practice using filters like unseen, previously wrong, due, or flagged
- `Exam`: exam-style session flow
- Background learner support:
  - objective-code mastery autopilot
  - confusion-pair drills
  - pass prediction
  - concept mistake clustering
  - transfer-strength scoring
  - freshness decay
  - difficulty calibration
  - burnout detection
  - source-agreement and source-trust weighting
- Runtime safety:
  - autosave after answers
  - resumable sessions
  - progress backups
  - checkpoint files
  - bad JSON quarantine / recovery
- Content safety:
  - validator and lint report
  - duplicate suppression
  - issue reporting and exclusion from scoring

**Why Smart Practice Is The Core**

`Smart Practice` is the strongest part of the engine. It is built to feel like a focused tutor running quietly in the background, not just a random question picker.

It now weighs learner memory, missed concepts, prerequisite gaps, source trust, question quality, transfer weakness, repeated confusion, and delayed-review timing before shaping a set. The goal is simple: spend fewer questions on noise and more questions on the exact concepts most likely to improve retention, recovery, and exam readiness.

Smart Practice also keeps the study session controlled. A `25` question set stays a `25` question set, adaptive follow-ups compete for space inside the limit, and protected roles keep the set balanced between weak repair, due retention, coverage, transfer checks, and controlled stretch.

Behind the scenes, the engine keeps improving its decisions with policy governance, concept-graph diagnosis, question information value, quality scoring, and later-outcome measurement. In plain English: it tries to learn why you missed something, pick the next best question, and avoid drilling bad or low-value items too hard.

**How The App Works**

At startup the app loads the default merged bank, restores saved configuration, and waits in a blank ready state until you start a set.

During study:

- each answer updates progress
- unfinished sessions autosave and can be resumed
- Smart Practice can insert a limited number of targeted follow-up questions
- progress, session, checkpoint, and backup file writes are centralized through the runtime persistence layer

The app keeps learner-facing UI simple while doing most adaptation in the background.

**Running The App**

Recommended launch options on Windows:

1. Double-click `security_test_app_windows_v8.pyw`
2. Or run `run_windows_v8.bat`
3. Or from a terminal:

```powershell
py app.py
```

If you want the launcher without a console window, use:

```powershell
pyw app.py
```

**Basic Usage**

1. Launch the app.
2. Choose a mode such as `Smart Practice`.
3. Pick a question count like `25` or `50`.
4. Start the set.
5. Answer questions and let the app autosave progress/session state.
6. Close the app at any time to resume later.

Useful behaviors:

- `Smart Practice` stays capped instead of expanding without limit
- closing the app saves progress and session state
- `Reported Issues` lets you quarantine questionable source items
- `Settings > Reset All Progress...` clears learner progress, sessions, rewards, flags, reports, and checkpoints for a fresh user
- builder/sidebar can collapse while you study

**Saved Data**

Runtime data is stored under:

- source/dev runs: `user_data/`
- packaged EXE runs: `%LOCALAPPDATA%\SecurityTestingEngine\`

Important subfolders:

- `user_data/backups/`: progress backups
- `user_data/checkpoints/`: periodic checkpoints
- `user_data/logs/`: app log output

Main runtime files include:

- progress JSON
- session JSON
- config JSON

The app also keeps compatibility logic for older saved session formats through session snapshot migration.

**Developer Commands**

Run tests:

```powershell
py -m unittest discover -s tests -v
```

Run the smoke test:

```powershell
py tools\smoke_test.py
```

Run bank validation:

```powershell
py tools\validate_bank.py public_sy0701_bank_v4_plus_studyguide_clean.json
```

Run the benchmark guard:

```powershell
py tools\benchmark_engine.py --count 50 --repeat 3 --assert-pool-max 4 --assert-analytics-max 3
```

Run the code-quality checks:

```powershell
py tools\run_quality_checks.py
```

Build the Windows release:

```powershell
build_windows_v8.bat
```

The Windows release folder is intentionally clean: `release\SecurityTestingEngine\` contains only `SecurityTestingEngine.exe`. The default question bank is bundled into the executable, and runtime progress/session data is written to local app data instead of beside the EXE.

If the repo is kept inside a clean app shell folder, `tools\build_release.py` also refreshes the root `SecurityTestingEngine.exe` and `README - Start Here.txt`. Packaged builds can automatically migrate stronger legacy progress from `Project Files\user_data` into `%LOCALAPPDATA%\SecurityTestingEngine\` when the packaged runtime has little or no progress.

**Project Layout**

- `app.py`: app bootstrap and top-level UI assembly
- `app_*_mixin.py`: feature-specific app behavior split by concern
- `question_bank.py`: bank loading, cleanup, and adaptive answer ordering
- `progress_store.py`: per-question progress logic
- `session_store.py`: session snapshot helpers and migration
- `runtime_persistence.py`: centralized runtime disk I/O facade
- `save_queue.py`: deferred autosave queue
- `tools/`: validation, import, benchmark, build, and utility scripts
- `tests/`: unit and GUI regression coverage
- `reports/`: generated reports such as validation and benchmark output

**Project Quality Status**

The repo includes:

- unit tests
- GUI regression tests
- smoke test
- benchmark regression guard
- `ruff`, `black`, and `mypy` checks for the maintained typed core

This gives the project a decent safety net for both learner-facing behavior and bank/persistence tooling.

**Notes**

- This project is built for study support, not as an official CompTIA product.
- Question quality can still vary by source, which is why validation, trust weighting, and issue reporting are built in.
- The merged bank is cleaned and validated, but source review is still an ongoing process.
