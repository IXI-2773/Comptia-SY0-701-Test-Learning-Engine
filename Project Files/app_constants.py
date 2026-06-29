MODE_PRACTICE = 'Practice'
MODE_SMART_PRACTICE = 'Smart Practice'
MODE_EXAM = 'Exam'

QUESTION_TAG_TWIN = 'Question twin'
QUESTION_TAG_CONFUSION_PAIR = 'Confusion pair drill'
QUESTION_TAG_DELAYED_RECALL_PROBE = 'Delayed recall probe'
QUESTION_TAG_RETRIEVAL_RAMP = 'Retrieval ramp'
QUESTION_TAG_TRANSFER_CHECK = 'Transfer check'
QUESTION_TAG_WRONG_ANSWER_MEMORY = 'Wrong-answer memory'
QUESTION_TAG_BOSS_ROUND = 'Boss round'
QUESTION_TAG_STEALTH_CHECKPOINT = 'Stealth checkpoint'
QUESTION_TAG_STREAK_RESCUE_PREFIX = 'Streak rescue: '

SESSION_SOURCE_OPTIONS = ['All', 'Unseen', 'Previously answered', 'Previously wrong', 'Due/flagged weak']
STATUS_FILTER_OPTIONS = [
    'All questions',
    'Unanswered',
    'Answered in session',
    'Correct in session',
    'Wrong in session',
    'Previously wrong',
    'Flagged',
    'Due review',
    'Suspended',
    'With issues',
]
STATUS_FILTER_ALIASES = {
    'Answered': 'Answered in session',
    'Correct': 'Correct in session',
    'Wrong': 'Wrong in session',
}

TRAP_WORD_PATTERNS = [
    ('best', r'\bbest\b'),
    ('most', r'\bmost\b'),
    ('least', r'\bleast\b'),
    ('except', r'\bexcept\b'),
    ('not', r'\bnot\b'),
    ('first', r'\bfirst\b'),
    ('next', r'\bnext\b'),
    ('primary', r'\bprimary\b'),
    ('initial', r'\binitial\b'),
    ('immediate', r'\bimmediate(?:ly)?\b'),
]

ABSOLUTE_DISTRACTOR_WORDS = {'all', 'always', 'never', 'only', 'every', 'none'}
REWARD_INTENSITY_OPTIONS = ['Light', 'Standard', 'High']
QUEST_COUNT_OPTIONS = ['1', '2', '3', '4', '5']

QUEST_VARIANTS = [
    {'key': 'answered_5', 'title': 'Warm Up', 'kind': 'answered_total', 'target': 5},
    {'key': 'answered_10', 'title': 'Study Flow', 'kind': 'answered_total', 'target': 10},
    {'key': 'answered_15', 'title': 'Deep Run', 'kind': 'answered_total', 'target': 15},
    {'key': 'correct_4', 'title': 'Steady Hand', 'kind': 'correct_total', 'target': 4},
    {'key': 'correct_7', 'title': 'Sharp Seven', 'kind': 'correct_total', 'target': 7},
    {'key': 'correct_10', 'title': 'Ten Down', 'kind': 'correct_total', 'target': 10},
    {'key': 'streak_3_quest', 'title': 'Clean 3', 'kind': 'correct_streak', 'target': 3},
    {'key': 'streak_5_quest', 'title': 'Clean 5', 'kind': 'correct_streak', 'target': 5},
    {'key': 'streak_7_quest', 'title': 'Clean 7', 'kind': 'correct_streak', 'target': 7},
    {'key': 'sure_3', 'title': 'Sure Start', 'kind': 'sure_correct', 'target': 3},
    {'key': 'sure_5', 'title': 'Sure Stack', 'kind': 'sure_correct', 'target': 5},
    {'key': 'sure_8', 'title': 'Sure Surge', 'kind': 'sure_correct', 'target': 8},
    {'key': 'recovery_1', 'title': 'Bounce Back', 'kind': 'recovery_hits', 'target': 1},
    {'key': 'recovery_2', 'title': 'Recovery Pair', 'kind': 'recovery_hits', 'target': 2},
    {'key': 'recovery_3', 'title': 'Weak No More', 'kind': 'recovery_hits', 'target': 3},
    {'key': 'domains_2', 'title': 'Cross-Train 2', 'kind': 'domain_spread', 'target': 2},
    {'key': 'domains_3', 'title': 'Cross-Train 3', 'kind': 'domain_spread', 'target': 3},
    {'key': 'domains_4', 'title': 'Cross-Train 4', 'kind': 'domain_spread', 'target': 4},
    {'key': 'weak_attempts_2', 'title': 'Face the Weak', 'kind': 'weak_attempts', 'target': 2},
    {'key': 'weak_attempts_4', 'title': 'Weak Hunter', 'kind': 'weak_attempts', 'target': 4},
    {'key': 'due_correct_1', 'title': 'Due Diligence', 'kind': 'due_correct', 'target': 1},
    {'key': 'perfect_focus_5', 'title': 'Perfect Focus', 'kind': 'perfect_focus', 'target': 5},
]

MILESTONE_SPECS = [
    ('answered_25', '25 Answered', 'total_answered', 25),
    ('answered_100', '100 Answered', 'total_answered', 100),
    ('answered_250', '250 Answered', 'total_answered', 250),
    ('recovered_10', '10 Recoveries', 'total_recovered', 10),
    ('recovered_50', '50 Recoveries', 'total_recovered', 50),
    ('sessions_5', '5 Sessions', 'sessions_completed', 5),
    ('sessions_20', '20 Sessions', 'sessions_completed', 20),
    ('perfect_3', '3 Perfect Focus Sessions', 'perfect_sessions', 3),
    ('domains_3', '3 Domains Touched', 'domain_count', 3),
]
