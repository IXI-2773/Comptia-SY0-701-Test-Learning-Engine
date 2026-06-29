Security Testing Engine v8

What changed:
- version 8 branding
- Smart Practice starts through a background builder so the visible app stays responsive
- adaptive memory tutor signals for concept memory, retrieval ramps, and wrong-answer memory
- expanded analytics and learner-retention scoring
- cleaned merged default bank

Files needed in same folder:
- security_test_app_windows_v8.py
- public_sy0701_bank_v4_plus_studyguide_clean.json
- run_windows_v8.bat (optional)
- build_windows_v8.bat (optional)

Run on Windows:
- double-click run_windows_v8.bat
or
- python security_test_app_windows_v8.py

Build EXE:
- double-click build_windows_v8.bat
or run from Anaconda Prompt.

Notes:
- Smart Practice now shows a building message instead of appearing frozen.
- Practice mode shows correctness immediately.
- Exam mode records answers but hides correctness/explanations until Finish Exam.
- Weak retest uses wrong answers, flagged items, and weak-domain coverage to build a focused set.
