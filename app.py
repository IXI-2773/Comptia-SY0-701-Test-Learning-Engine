import copy
import json
import logging
import os
import re
import shutil
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import cast

BASE_DIR = Path(__file__).resolve().parent
LEGACY_PROJECT_ROOT = BASE_DIR.parent
if not (BASE_DIR / "smart_practice_concept_graph.py").exists() and str(LEGACY_PROJECT_ROOT) not in sys.path:
    # Support the older nested source layout where Smart Practice modules lived one level above app.py.
    sys.path.insert(0, str(LEGACY_PROJECT_ROOT))

from app_analytics_mixin import AnalyticsMixin
from app_constants import (
    ABSOLUTE_DISTRACTOR_WORDS,
    MODE_EXAM,
    MODE_PRACTICE,
    MODE_SMART_PRACTICE,
    SESSION_SOURCE_OPTIONS,
    STATUS_FILTER_ALIASES,
    STATUS_FILTER_OPTIONS,
    TRAP_WORD_PATTERNS,
)
from app_constants import (
    MILESTONE_SPECS as APP_MILESTONE_SPECS,
)
from app_constants import (
    QUEST_VARIANTS as APP_QUEST_VARIANTS,
)
from app_game_mixin import GameRewardsMixin
from app_info import APP_NAME, APP_VERSION
from app_question_flow_mixin import QuestionFlowMixin
from app_question_render_mixin import QuestionRenderMixin
from app_session_builder_mixin import SessionBuilderMixin
from app_session_persistence_mixin import SessionPersistenceMixin
from bank_models import QuestionBankData
from config_store import DEFAULT_CONFIG, load_config, save_config
from progress_models import (
    IssueReport,
    ProgressMeta,
    ProgressSummary,
    issue_report_from_question,
    normalize_progress_meta,
)
from progress_store import (
    CONFIDENCE_OPTIONS,
    PROGRESS_VERSION,
    SESSION_SOURCE_ALIASES,
    ProgressQuestionMap,
    ProgressRecord,
    append_progress_history,
    blank_progress,
    default_progress_record,
    is_active_weak,
    is_ever_wrong,
    is_review_due,
    is_suspended,
    normalize_progress_record,
    now_iso,
    question_key,
    set_progress_flag,
    set_progress_suspended,
    update_progress_record,
)
from question_bank import adaptive_shuffle_question, load_bank, stable_shuffle_question
from question_widgets import ChoiceRow
from render_cache import QuestionRenderCache
from runtime_persistence import RuntimePersistence
from save_queue import DeferredSaveQueue
from session_models import (
    QuestionHistoryEvent,
    QuestionRuntimeState,
    QuestProgressState,
    SessionAnswerEvent,
    clear_runtime_answer_state,
)
from smart_practice_cache import SmartPracticePrewarmService
from smart_practice_measurement import event_prediction_fields
from storage_utils import safe_write_json, setup_logging
from ui_theme import (  # noqa: F401 - public test/theme compatibility exports
    AMBER,
    BG,
    BLUE,
    BORDER,
    CARD,
    DARK,
    GREEN,
    HOVER_BADGE,
    HOVER_BG,
    HOVER_BORDER,
    LIGHT_BLUE,
    LIGHT_YELLOW,
    MUTED,
    RED,
    SIDEBAR,
    TEXT,
)
from ui_typography import (
    QUESTION_EXPLANATION_FONT,
    QUESTION_META_FONT,
    QUESTION_META_STRIP_FONT,
    QUESTION_PROMPT_FONT,
    QUESTION_STATUS_FONT,
    TOPBAR_TITLE_FONT,
)
from widget_models import (
    AnalyticsWidgetRegistry,
    IssueReviewWidgetRegistry,
    RewardHistoryWidgetRegistry,
    ScreenshotReviewWidgetRegistry,
)
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else BASE_DIR


def resolve_user_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / "SecurityTestingEngine"
    return APP_DIR / "user_data"


def first_existing_path(*paths: Path) -> Path:
    for path in paths:
        if path.exists():
            return path
    return paths[0]


def progress_file_strength(path: Path) -> tuple[int, int, int, int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0, 0, 0, 0
    meta = data.get("meta") if isinstance(data, dict) else {}
    questions = len(data.get("questions") or {}) if isinstance(data, dict) else 0
    history = len(data.get("history") or []) if isinstance(data, dict) else 0
    xp = int((meta or {}).get("xp", 0) or 0) if isinstance(meta, dict) else 0
    sessions = len((meta or {}).get("session_history") or []) if isinstance(meta, dict) else 0
    return questions * 5 + history * 3 + xp + sessions * 50, questions, history, xp


def best_progress_strength(user_data_dir: Path) -> tuple[int, int, int, int, Path | None]:
    best = (0, 0, 0, 0, None)
    if not user_data_dir.exists():
        return best
    for path in user_data_dir.glob("*_progress.json"):
        strength, questions, history, xp = progress_file_strength(path)
        if strength > best[0]:
            best = (strength, questions, history, xp, path)
    return best


def packaged_legacy_user_data_dirs() -> list[Path]:
    if not getattr(sys, "frozen", False):
        return []
    return [
        APP_DIR / "Project Files" / "user_data",
        APP_DIR / "user_data",
    ]


def auto_migrate_packaged_runtime_data(target_dir: Path) -> str:
    source_candidates = [path for path in packaged_legacy_user_data_dirs() if path.exists()]
    if not source_candidates:
        return ""
    target_strength, target_questions, _target_history, _target_xp, _target_path = best_progress_strength(target_dir)
    source_strengths = [(best_progress_strength(path), path) for path in source_candidates]
    (source_strength, source_questions, source_history, source_xp, _source_path), source_dir = max(
        source_strengths, key=lambda item: item[0][0]
    )
    if source_strength <= 0 or source_strength <= target_strength:
        return ""
    if target_strength > 0 and target_questions > 5 and source_strength < target_strength * 3:
        return ""

    stamp = time.strftime("%Y%m%d_%H%M%S")
    if target_dir.exists() and any(target_dir.iterdir()):
        backup_dir = target_dir.with_name(f"{target_dir.name}_before_auto_migration_{stamp}")
        shutil.copytree(target_dir, backup_dir, dirs_exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)
    for child in target_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in source_dir.iterdir():
        destination = target_dir / child.name
        if child.is_dir():
            shutil.copytree(child, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(child, destination)
    return (
        f"Imported existing progress from {source_dir}. "
        f"Recovered {source_questions} question records, {source_history} history events, and {source_xp} XP."
    )


USER_DATA_DIR = resolve_user_data_dir()
CHECKPOINT_DIR = USER_DATA_DIR / "checkpoints"
BACKUP_DIR = USER_DATA_DIR / "backups"
CONFIG_PATH = USER_DATA_DIR / "config.json"
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
RUNTIME_MIGRATION_NOTICE = auto_migrate_packaged_runtime_data(USER_DATA_DIR)
DEFAULT_BANK_CLEAN = first_existing_path(
    APP_DIR / "public_sy0701_bank_v4_clean.json",
    RESOURCE_DIR / "public_sy0701_bank_v4_clean.json",
)
DEFAULT_BANK_MERGED = first_existing_path(
    APP_DIR / "public_sy0701_bank_v4_plus_studyguide_clean.json",
    RESOURCE_DIR / "public_sy0701_bank_v4_plus_studyguide_clean.json",
)
DEFAULT_BANK_LEGACY = first_existing_path(
    APP_DIR / "public_sy0701_bank_v4.json",
    RESOURCE_DIR / "public_sy0701_bank_v4.json",
)
DEFAULT_BANK = first_existing_path(DEFAULT_BANK_MERGED, DEFAULT_BANK_CLEAN, DEFAULT_BANK_LEGACY)
LOG_PATH = setup_logging(USER_DATA_DIR)
logging.info("%s %s starting", APP_NAME, APP_VERSION)

QUEST_VARIANTS = APP_QUEST_VARIANTS
MILESTONE_SPECS = APP_MILESTONE_SPECS


class TestingEngineApp(
    SessionPersistenceMixin,
    GameRewardsMixin,
    QuestionRenderMixin,
    SessionBuilderMixin,
    QuestionFlowMixin,
    AnalyticsMixin,
):
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.config = load_config(CONFIG_PATH)
        self.startup_warnings = self.startup_check()
        self.root.geometry(str(self.config.get("window_geometry") or "1500x940"))
        self.root.minsize(760, 620)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close_app)
        self.root.bind("<Configure>", self._on_root_configure)
        self.user_data_dir = USER_DATA_DIR
        self.checkpoint_dir = CHECKPOINT_DIR
        self.backup_dir = BACKUP_DIR
        self.persistence = RuntimePersistence(checkpoint_dir=self.checkpoint_dir, backup_dir=self.backup_dir)

        self.bank_path = DEFAULT_BANK if DEFAULT_BANK.exists() else None
        self.session_path = None
        self.progress_path = None
        self.progress_data = blank_progress(app_version=APP_VERSION)
        self.data: QuestionBankData | None = None
        self.master_questions: list[QuestionRuntimeState] = []
        self.questions: list[QuestionRuntimeState] = []
        self.index = 0
        self.visible_indices = []
        self.elapsed_base = 0
        self.clock_started_at = time.time()
        self.checkpoints_saved = set()
        self.last_checkpoint_notice = ""
        self.analytics_window = None
        self.analytics_widgets: AnalyticsWidgetRegistry = cast(AnalyticsWidgetRegistry, {})
        self.mousewheel_bound = False
        self.active_source_label = "Full bank"
        self.save_queue = DeferredSaveQueue(self.root)
        self.last_question_list_signature = None
        self.last_progress_snapshot = None
        self.last_session_snapshot = None
        self.last_config_snapshot = None
        self.analytics_cache_key = None
        self.analytics_cache_payload = None
        self.analytics_source_cache_key = None
        self.analytics_source_cache_payload = None
        self.smart_practice_signal_cache_key = None
        self.smart_practice_signal_cache_payload = None
        self.smart_practice_pool_cache = {}
        self.smart_practice_prewarm = None
        self.render_cache = QuestionRenderCache()
        self.last_render_snapshot = None
        self.followup_candidate_index = None
        self.followup_candidate_index_signature = None
        self.progress_summary_cache_key = None
        self.progress_summary_cache_payload = None
        self.answer_feedback_anchor = None
        self.answer_feedback_popover = None
        self.answer_feedback_buttons = []
        self.pending_feedback_request = None
        self.answer_order_epoch = 0
        self.unlocked_rewards = set()
        self.session_rewards = []
        self.reward_banner_after_id = None
        self.answer_toast_after_id = None
        self.answer_toast_text = ""
        self.answer_toast_kind = "answer"
        self.reward_badges_text = "Rewards: none yet"
        self.reward_badges_fg = MUTED
        self.reward_history_window = None
        self.reward_history_widgets: RewardHistoryWidgetRegistry = cast(RewardHistoryWidgetRegistry, {})
        self.issue_review_window = None
        self.issue_review_widgets: IssueReviewWidgetRegistry = cast(IssueReviewWidgetRegistry, {})
        self.screenshot_review_window = None
        self.screenshot_review_widgets: ScreenshotReviewWidgetRegistry = cast(ScreenshotReviewWidgetRegistry, {})
        self.game_settings_window = None
        self.current_quests: list[QuestProgressState] = []
        self.quest_completion_keys = set()
        self.session_boss_markers = set()
        self.session_stealth_markers = set()
        self.session_combo_burst_markers = set()
        self.session_xp_gained = 0
        self.session_completion_signature = None
        self.last_session_summary = None
        self.last_reward_feedback_at = 0.0
        self.pass_score_victory_unlocked = False
        self.victory_after_ids = []
        self.answer_feedback_after_ids = []
        self.answer_result_after_ids = []
        self.study_hud_pulse_after_ids = []
        self.auto_next_after_id = None
        self.active_question_started_qnum = None
        self.active_question_started_at = None
        self.scroll_to_top_on_render = False
        self.question_list_dirty = True
        self.session_answer_history: list[SessionAnswerEvent] = []
        self.rescue_domains_triggered = set()
        self.session_base_question_count = None
        self.session_question_limit = None
        self.session_restore_question_numbers: list[int] = []
        self.current_builder_context_data = {}
        self.sidebar_visible = True
        self.sidebar_auto_collapsed = False
        self.submit_btn_visible = False
        self.sidebar_width_options = {"Full": 320, "Narrow": 248}
        self.sidebar_width_mode = str(self.config.get("sidebar_width_mode", "Full") or "Full")

        self.domain_filter_var = tk.StringVar(value=str(self.config.get("last_domain") or "All domains"))
        self.topic_filter_var = tk.StringVar(value=str(self.config.get("last_topic") or "All topics"))
        self.status_filter_var = tk.StringVar(value=self.normalize_status_filter(self.config.get("last_status")))
        self.jump_var = tk.StringVar()
        self.session_mode_var = tk.StringVar(value=MODE_SMART_PRACTICE)
        self.session_count_var = tk.StringVar(value=str(self.config.get("session_count") or "25"))
        self.session_source_var = tk.StringVar(value=self.normalize_session_source(self.config.get("session_source")))
        self.session_random_var = tk.BooleanVar(value=bool(self.config.get("random_order")))
        self.auto_next_correct_var = tk.BooleanVar(value=bool(self.config.get("auto_next_correct")))
        self.explanation_recall_var = tk.BooleanVar(value=bool(self.config.get("explanation_recall_mode", True)))
        self.compact_review_var = tk.BooleanVar(value=bool(self.config.get("compact_review_mode", True)))
        self.dense_answers_var = tk.BooleanVar(value=bool(self.config.get("dense_answers_mode", False)))
        self.gamification_enabled_var = tk.BooleanVar(value=bool(self.config.get("gamification_enabled", True)))
        self.celebration_popups_var = tk.BooleanVar(value=bool(self.config.get("celebration_popups", True)))
        self.reward_sounds_var = tk.BooleanVar(value=bool(self.config.get("reward_sounds", True)))
        self.micro_feedback_var = tk.BooleanVar(value=bool(self.config.get("micro_feedback", True)))
        self.boss_rounds_enabled_var = tk.BooleanVar(value=bool(self.config.get("boss_rounds_enabled", True)))
        self.reward_intensity_var = tk.StringVar(
            value=str(self.config.get("reward_intensity", "Standard") or "Standard")
        )
        self.quest_count_var = tk.StringVar(value=str(self.config.get("quest_count", "3") or "3"))
        self.active_session_mode = MODE_PRACTICE
        self.exam_reveal = True
        self.general_explanation_expanded = True

        self._build_ui()
        self.smart_practice_prewarm = SmartPracticePrewarmService(
            self.root,
            self._publish_smart_practice_signal_snapshot,
        )
        self.on_session_mode_change()
        self._bind_hotkeys()
        self.show_startup_warnings()
        self._load_initial_bank()
        self._tick()

    def _build_ui(self):
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=0)
        file_menu.add_command(label="Open Question Bank JSON...", command=self.open_bank)
        file_menu.add_command(label="Reload Current Bank", command=self.reload_bank)
        file_menu.add_separator()
        file_menu.add_command(label="Save Session Now", command=lambda: self.save_session(show_notice=True))
        file_menu.add_command(label="Backup Progress...", command=self.backup_progress_manual)
        file_menu.add_command(label="Restore Progress...", command=self.restore_progress_manual)
        file_menu.add_command(label="Reset Preferences", command=self.reset_preferences)
        file_menu.add_command(label="Reset Session", command=self.reset_session)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.close_app)
        menu.add_cascade(label="File", menu=file_menu)
        view_menu = tk.Menu(menu, tearoff=0)
        view_menu.add_command(label="Analytics Dashboard", command=self.open_analytics_window)
        view_menu.add_command(label="Rewards / History", command=self.open_reward_history_window)
        view_menu.add_command(label="Reported Issues", command=self.open_issue_review_window)
        view_menu.add_command(label="Screenshot Review", command=self.open_screenshot_review_window)
        menu.add_cascade(label="View", menu=view_menu)
        settings_menu = tk.Menu(menu, tearoff=0)
        settings_menu.add_command(label="Game Layer Settings", command=self.open_game_settings_window)
        settings_menu.add_separator()
        settings_menu.add_command(label="Reset All Progress...", command=self.reset_all_progress)
        menu.add_cascade(label="Settings", menu=settings_menu)
        help_menu = tk.Menu(menu, tearoff=0)
        help_menu.add_command(label="Keyboard Shortcuts", command=self.show_shortcuts)
        help_menu.add_command(label="About", command=self.show_about)
        menu.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=menu)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "Blue.Horizontal.TProgressbar",
            troughcolor="#d9d9d9",
            bordercolor="#d9d9d9",
            background=BLUE,
            lightcolor=BLUE,
            darkcolor=BLUE,
        )

        self.topbar = tk.Frame(self.root, bg=BLUE, height=46)
        self.topbar.pack(fill="x")
        self.topbar.pack_propagate(False)
        self.topbar_title = tk.Label(
            self.topbar,
            text="Security Testing Engine",
            bg=BLUE,
            fg="white",
            font=TOPBAR_TITLE_FONT,
            anchor="w",
            padx=16,
        )
        self.topbar_title.pack(side="left", fill="both", expand=True)
        self.sidebar_width_btn = tk.Menubutton(
            self.topbar,
            text="Builder: Full",
            font=("Segoe UI", 8, "bold"),
            bd=0,
            bg="#edf4fb",
            fg=BLUE,
            activebackground="#dfeaf7",
            activeforeground=BLUE,
            padx=10,
            pady=5,
        )
        self.sidebar_width_menu = tk.Menu(self.sidebar_width_btn, tearoff=0)
        self.sidebar_width_menu.add_command(label="Full width", command=lambda: self.set_sidebar_width_mode("Full"))
        self.sidebar_width_menu.add_command(label="Narrow width", command=lambda: self.set_sidebar_width_mode("Narrow"))
        self.sidebar_width_btn.configure(menu=self.sidebar_width_menu)
        self.sidebar_width_btn.pack(side="right", padx=(0, 8), pady=8)
        self.sidebar_toggle_btn = tk.Button(
            self.topbar,
            text="Hide Builder",
            font=("Segoe UI", 8, "bold"),
            bd=0,
            bg="#edf4fb",
            fg=BLUE,
            activebackground="#dfeaf7",
            activeforeground=BLUE,
            padx=10,
            pady=5,
            command=self.toggle_sidebar,
        )
        self.sidebar_toggle_btn.pack(side="right", padx=12, pady=8)

        self.page = tk.Frame(self.root, bg=BG)
        self.page.pack(fill="both", expand=True)
        self.sidebar = tk.Frame(self.page, bg=SIDEBAR, width=self.sidebar_width_options["Full"])
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self.main = tk.Frame(self.page, bg=BG)
        self.main.pack(side="right", fill="both", expand=True)
        self.set_sidebar_width_mode(self.sidebar_width_mode, save=False)
        self._build_sidebar()
        self._build_main()

    def toggle_sidebar(self):
        self.set_sidebar_visible(not self.sidebar_visible)

    def normalize_sidebar_width_mode(self, value):
        value = str(value or "").strip().title()
        return value if value in self.sidebar_width_options else "Full"

    def set_sidebar_width_mode(self, mode, save=True):
        mode = self.normalize_sidebar_width_mode(mode)
        self.sidebar_width_mode = mode
        width = self.sidebar_width_options.get(mode, self.sidebar_width_options["Full"])
        if hasattr(self, "sidebar"):
            self.sidebar.configure(width=width)
            self.sidebar.pack_propagate(False)
        if hasattr(self, "sidebar_width_btn"):
            self.sidebar_width_btn.configure(text=f"Builder: {mode}")
        if save:
            self.save_app_config()

    def set_sidebar_visible(self, visible):
        visible = bool(visible)
        self.sidebar_visible = visible
        self.sidebar_auto_collapsed = False
        if visible:
            self.sidebar.configure(
                width=self.sidebar_width_options.get(self.sidebar_width_mode, self.sidebar_width_options["Full"])
            )
            self.sidebar.pack(side="left", fill="y", before=self.main)
            self.sidebar.pack_propagate(False)
        else:
            self.sidebar.pack_forget()
        if hasattr(self, "sidebar_toggle_btn"):
            self.sidebar_toggle_btn.configure(text=("Hide Builder" if visible else "Show Builder"))

    def startup_check(self):
        warnings = []
        for folder in (USER_DATA_DIR, CHECKPOINT_DIR, BACKUP_DIR, USER_DATA_DIR / "logs"):
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                warnings.append(f"Could not create folder: {folder}\n{e}")
        if not DEFAULT_BANK.exists():
            warnings.append(f"Default question bank was not found:\n{DEFAULT_BANK}")
        if RUNTIME_MIGRATION_NOTICE:
            warnings.append(RUNTIME_MIGRATION_NOTICE)
        try:
            probe = USER_DATA_DIR / ".write_test.tmp"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except Exception as e:
            warnings.append(f"User data folder is not writable:\n{USER_DATA_DIR}\n{e}")
        return warnings

    def show_startup_warnings(self):
        if self.startup_warnings:
            messagebox.showwarning("Startup Check", "\n\n".join(self.startup_warnings))

    def normalize_session_source(self, value):
        source = SESSION_SOURCE_ALIASES.get(str(value or "").strip(), str(value or "").strip())
        return source if source in SESSION_SOURCE_OPTIONS else "All"

    def normalize_status_filter(self, value):
        status = STATUS_FILTER_ALIASES.get(str(value or "").strip(), str(value or "").strip())
        return status if status in STATUS_FILTER_OPTIONS else "All questions"

    def collect_config(self):
        analytics_geometry = self.config.get("analytics_geometry", DEFAULT_CONFIG["analytics_geometry"])
        if self.analytics_window and self.analytics_window.winfo_exists():
            analytics_geometry = self.analytics_window.geometry()
        return {
            "window_geometry": self.root.geometry(),
            "analytics_geometry": analytics_geometry,
            "analytics_domain_widths": self.capture_tree_widths("domain_tree"),
            "analytics_topic_widths": self.capture_tree_widths("topic_tree"),
            "session_count": self.session_count_var.get(),
            "session_source": self.normalize_session_source(self.session_source_var.get()),
            "random_order": self.session_random_var.get(),
            "auto_next_correct": self.auto_next_correct_var.get(),
            "explanation_recall_mode": self.explanation_recall_var.get(),
            "compact_review_mode": self.compact_review_var.get(),
            "dense_answers_mode": self.dense_answers_var.get(),
            "gamification_enabled": self.gamification_enabled_var.get(),
            "reward_intensity": self.reward_intensity_var.get(),
            "celebration_popups": self.celebration_popups_var.get(),
            "reward_sounds": self.reward_sounds_var.get(),
            "micro_feedback": self.micro_feedback_var.get(),
            "boss_rounds_enabled": self.boss_rounds_enabled_var.get(),
            "quest_count": self.quest_count_var.get(),
            "sidebar_width_mode": self.sidebar_width_mode,
            "last_domain": self.domain_filter_var.get(),
            "last_topic": self.topic_filter_var.get(),
            "last_status": self.normalize_status_filter(self.status_filter_var.get()),
            "general_explanation_expanded": True,
        }

    def save_app_config(self):
        try:
            self.save_queue.cancel("config")
            config = self.collect_config()
            snapshot = json.dumps(config, sort_keys=True, separators=(",", ":"))
            if snapshot == self.last_config_snapshot:
                self.config = config
                return
            self.config = config
            save_config(CONFIG_PATH, self.config)
            self.last_config_snapshot = snapshot
        except Exception:
            logging.exception("Failed to save config: %s", CONFIG_PATH)

    def _on_root_configure(self, event=None):
        if event is not None and event.widget != self.root:
            return
        if event is not None:
            self._apply_responsive_window_layout(event.width)
        self._schedule_config_save()

    def _apply_responsive_window_layout(self, width):
        width = int(width or 0)
        if not width or not hasattr(self, "sidebar"):
            return

        narrow = width < 1040
        if narrow and self.sidebar_visible:
            self.sidebar_auto_collapsed = True
            self.sidebar_visible = False
            self.sidebar.pack_forget()
            self.sidebar_toggle_btn.configure(text="Show Builder")
        elif not narrow and self.sidebar_auto_collapsed:
            self.sidebar_auto_collapsed = False
            self.sidebar_visible = True
            self.sidebar.configure(
                width=self.sidebar_width_options.get(
                    self.sidebar_width_mode,
                    self.sidebar_width_options["Full"],
                )
            )
            self.sidebar.pack(side="left", fill="y", before=self.main)
            self.sidebar.pack_propagate(False)
            self.sidebar_toggle_btn.configure(text="Hide Builder")

        if hasattr(self, "sidebar_width_btn"):
            if width < 900:
                self.sidebar_width_btn.pack_forget()
            elif not self.sidebar_width_btn.winfo_manager():
                self.sidebar_width_btn.pack(side="right", padx=(0, 8), pady=8)

        if hasattr(self, "topbar_title"):
            self.topbar_title.configure(
                text=(
                    "Security Testing Engine"
                    if width < 820
                    else (
                        f"Security Testing Engine - {self.active_session_mode}"
                        if self.questions
                        else "Security Testing Engine"
                    )
                ),
                padx=10 if width < 900 else 16,
            )

    def _schedule_config_save(self):
        self.save_queue.schedule("config", self.save_app_config, delay_ms=250)

    def _flush_scheduled_config_save(self):
        self.save_queue.flush("config")

    def schedule_progress_save(self, delay_ms=175):
        self.save_queue.schedule("progress", self.save_progress, delay_ms=delay_ms)

    def flush_scheduled_progress_save(self):
        self.save_queue.flush("progress")

    def close_app(self):
        try:
            if self.smart_practice_prewarm is not None:
                self.smart_practice_prewarm.close()
            self.save_queue.flush_all()
            self.save_session(show_notice=False)
            self.save_progress()
        except Exception:
            logging.exception("Failed to save runtime state during close.")
        self.save_app_config()
        self.root.destroy()

    def invalidate_learning_state(self, *, prewarm=True, prewarm_delay_ms=None):
        self.analytics_cache_key = None
        self.analytics_cache_payload = None
        self.analytics_source_cache_key = None
        self.analytics_source_cache_payload = None
        self.smart_practice_signal_cache_key = None
        self.smart_practice_signal_cache_payload = None
        self.smart_practice_pool_cache.clear()
        self.progress_summary_cache_key = None
        self.progress_summary_cache_payload = None
        self.last_question_list_signature = None
        self.last_render_snapshot = None
        self.render_cache.clear()
        if self.smart_practice_prewarm is not None:
            self.smart_practice_prewarm.invalidate()
        if prewarm and self.master_questions:
            self.schedule_smart_practice_prewarm(delay_ms=prewarm_delay_ms)

    def reset_preferences(self):
        if not messagebox.askyesno(
            "Reset preferences", "Reset saved app preferences to defaults? Progress and sessions will not be changed."
        ):
            return
        save_config(CONFIG_PATH, DEFAULT_CONFIG)
        self.config = DEFAULT_CONFIG.copy()
        self.session_count_var.set(self.config["session_count"])
        self.session_source_var.set(self.normalize_session_source(self.config["session_source"]))
        self.session_random_var.set(self.config["random_order"])
        self.auto_next_correct_var.set(self.config["auto_next_correct"])
        self.explanation_recall_var.set(self.config.get("explanation_recall_mode", True))
        self.compact_review_var.set(self.config.get("compact_review_mode", True))
        self.dense_answers_var.set(self.config.get("dense_answers_mode", False))
        self.gamification_enabled_var.set(self.config.get("gamification_enabled", True))
        self.reward_intensity_var.set(self.config.get("reward_intensity", "Standard"))
        self.celebration_popups_var.set(self.config.get("celebration_popups", True))
        self.reward_sounds_var.set(self.config.get("reward_sounds", True))
        self.micro_feedback_var.set(self.config.get("micro_feedback", True))
        self.boss_rounds_enabled_var.set(self.config.get("boss_rounds_enabled", True))
        self.quest_count_var.set(self.config.get("quest_count", "3"))
        self.set_sidebar_width_mode(self.config.get("sidebar_width_mode", "Full"), save=False)
        self.domain_filter_var.set(self.config["last_domain"])
        self.topic_filter_var.set(self.config["last_topic"])
        self.status_filter_var.set(self.normalize_status_filter(self.config["last_status"]))
        self.general_explanation_expanded = True
        self.root.geometry(self.config["window_geometry"])
        self.refresh_question_list()
        self.render_question()
        messagebox.showinfo("Reset preferences", "Preferences were reset.")

    def _delete_runtime_progress_files(self) -> list[Path]:
        targets: set[Path] = set()
        for pattern in ("*_progress.json", "*_session_*.json"):
            targets.update(path for path in self.user_data_dir.glob(pattern) if path.is_file())
        targets.update(path for path in self.checkpoint_dir.glob("*_checkpoint_*.json") if path.is_file())
        if self.bank_path:
            targets.add(self.legacy_progress_file_for_bank(self.bank_path))
            stem = self.runtime_bank_stem(self.bank_path)
            targets.update(path for path in self.bank_path.parent.glob(f"{stem}_*_session.json") if path.is_file())

        deleted: list[Path] = []
        for path in sorted(targets):
            try:
                path.unlink()
                deleted.append(path)
            except FileNotFoundError:
                continue
            except OSError:
                logging.exception("Failed to delete runtime progress file during reset: %s", path)
        return deleted

    def reset_all_progress(self):
        if not messagebox.askyesno(
            "Reset all progress",
            "Reset all learner progress, active sessions, rewards, flags, reports, and checkpoints? "
            "Question banks and app preferences will not be changed.",
        ):
            return
        if not messagebox.askyesno(
            "Confirm progress reset",
            "This makes the app behave like a fresh install for the next learner. Continue?",
        ):
            return

        self.save_queue.cancel("progress")
        self.save_queue.cancel("session")
        self.auto_backup_progress()
        deleted = self._delete_runtime_progress_files()

        self.progress_data = blank_progress(self.bank_path.name if self.bank_path else "", app_version=APP_VERSION)
        self._normalized_progress_questions_ref = None
        self.last_progress_snapshot = None
        self.last_session_snapshot = None

        if self.data:
            self.master_questions = self._clone_questions(self.data["questions"])
            self._reset_runtime_question_state(self.master_questions)
            self._rebuild_followup_candidate_index()

        self.clear_active_session(reset_clock=True)
        self.save_progress()
        self.invalidate_learning_state(prewarm=True, prewarm_delay_ms=0)
        self.refresh_question_list()
        self.render_question()
        messagebox.showinfo(
            "Reset all progress",
            f"Progress has been reset. Removed {len(deleted)} saved progress/session/checkpoint file(s).",
        )

    def _build_sidebar(self):
        wrap = tk.Frame(self.sidebar, bg=SIDEBAR, padx=12, pady=12)
        wrap.pack(fill="both", expand=True)

        sess = tk.Frame(wrap, bg=LIGHT_BLUE, padx=10, pady=10, bd=1, relief="solid")
        sess.pack(fill="x", pady=(0, 10))
        tk.Label(sess, text="Session Builder", bg=LIGHT_BLUE, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Label(sess, text="Mode", bg=LIGHT_BLUE, fg=TEXT, font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(8, 0))
        self.mode_combo = ttk.Combobox(
            sess,
            textvariable=self.session_mode_var,
            state="readonly",
            values=[MODE_SMART_PRACTICE, MODE_PRACTICE, MODE_EXAM, "Weak retest", "Due review"],
        )
        self.mode_combo.pack(fill="x", pady=(3, 6))
        self.mode_combo.bind("<<ComboboxSelected>>", self.on_session_mode_change)
        tk.Label(sess, text="Question amount", bg=LIGHT_BLUE, fg=TEXT, font=("Segoe UI", 8, "bold")).pack(anchor="w")
        self.count_combo = ttk.Combobox(
            sess, textvariable=self.session_count_var, state="readonly", values=["25", "50", "90", "All visible"]
        )
        self.count_combo.pack(fill="x", pady=(3, 6))
        self.count_combo.bind("<<ComboboxSelected>>", lambda e: self.save_app_config())
        tk.Label(sess, text="Question source", bg=LIGHT_BLUE, fg=TEXT, font=("Segoe UI", 8, "bold")).pack(anchor="w")
        self.source_combo = ttk.Combobox(
            sess, textvariable=self.session_source_var, state="readonly", values=SESSION_SOURCE_OPTIONS
        )
        self.source_combo.pack(fill="x", pady=(3, 6))
        self.source_combo.bind("<<ComboboxSelected>>", lambda e: self.save_app_config())
        tk.Checkbutton(
            sess,
            text="Random question order",
            variable=self.session_random_var,
            bg=LIGHT_BLUE,
            fg=TEXT,
            activebackground=LIGHT_BLUE,
            anchor="w",
            command=self.save_app_config,
        ).pack(fill="x", pady=(0, 8))
        tk.Checkbutton(
            sess,
            text="Auto-next after correct",
            variable=self.auto_next_correct_var,
            bg=LIGHT_BLUE,
            fg=TEXT,
            activebackground=LIGHT_BLUE,
            anchor="w",
            command=self.save_app_config,
        ).pack(fill="x", pady=(0, 8))
        tk.Checkbutton(
            sess,
            text="Compact review mode",
            variable=self.compact_review_var,
            bg=LIGHT_BLUE,
            fg=TEXT,
            activebackground=LIGHT_BLUE,
            anchor="w",
            command=lambda: (self.save_app_config(), self.render_question()),
        ).pack(fill="x", pady=(0, 8))
        tk.Checkbutton(
            sess,
            text="Dense answers mode",
            variable=self.dense_answers_var,
            bg=LIGHT_BLUE,
            fg=TEXT,
            activebackground=LIGHT_BLUE,
            anchor="w",
            command=lambda: (self.save_app_config(), self.render_question()),
        ).pack(fill="x", pady=(0, 8))
        row = tk.Frame(sess, bg=LIGHT_BLUE)
        row.pack(fill="x")
        self.start_set_btn = tk.Button(
            row,
            text="START SET",
            font=("Segoe UI", 8, "bold"),
            bg=BLUE,
            fg="white",
            bd=0,
            padx=10,
            pady=6,
            command=self.start_custom_session,
        )
        self.start_set_btn.pack(side="left")
        self.full_bank_btn = tk.Button(
            row,
            text="FULL BANK",
            font=("Segoe UI", 8, "bold"),
            bg="#f7f9fc",
            fg=BLUE,
            bd=1,
            relief="solid",
            padx=10,
            pady=5,
            command=self.restore_full_bank,
        )
        self.full_bank_btn.pack(side="left", padx=(8, 0))
        quick = tk.Frame(sess, bg=LIGHT_BLUE)
        quick.pack(fill="x", pady=(8, 0))
        tk.Button(
            quick,
            text="MISSED",
            font=("Segoe UI", 8, "bold"),
            bg="#f7f9fc",
            fg=RED,
            bd=1,
            relief="solid",
            padx=8,
            pady=4,
            command=lambda: self.apply_status_filter("Wrong in session"),
        ).pack(side="left")
        tk.Button(
            quick,
            text="FLAGGED",
            font=("Segoe UI", 8, "bold"),
            bg="#f7f9fc",
            fg=BLUE,
            bd=1,
            relief="solid",
            padx=8,
            pady=4,
            command=lambda: self.apply_status_filter("Flagged"),
        ).pack(side="left", padx=(6, 0))
        tk.Button(
            quick,
            text="DUE",
            font=("Segoe UI", 8, "bold"),
            bg="#f7f9fc",
            fg=AMBER,
            bd=1,
            relief="solid",
            padx=8,
            pady=4,
            command=lambda: self.apply_status_filter("Due review"),
        ).pack(side="left", padx=(6, 0))

        tk.Label(wrap, text="Domain", bg=SIDEBAR, fg=TEXT, font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x")
        self.domain_combo = ttk.Combobox(wrap, textvariable=self.domain_filter_var, state="readonly")
        self.domain_combo.pack(fill="x", pady=(4, 10))
        self.domain_combo.bind("<<ComboboxSelected>>", self.on_filter_change)

        tk.Label(wrap, text="Topic", bg=SIDEBAR, fg=TEXT, font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x")
        self.topic_combo = ttk.Combobox(wrap, textvariable=self.topic_filter_var, state="readonly")
        self.topic_combo.pack(fill="x", pady=(4, 10))
        self.topic_combo.bind("<<ComboboxSelected>>", self.on_filter_change)

        tk.Label(wrap, text="Status", bg=SIDEBAR, fg=TEXT, font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x")
        self.status_combo = ttk.Combobox(
            wrap, textvariable=self.status_filter_var, state="readonly", values=STATUS_FILTER_OPTIONS
        )
        self.status_combo.pack(fill="x", pady=(4, 10))
        self.status_combo.bind("<<ComboboxSelected>>", self.on_filter_change)

        jump_frame = tk.Frame(wrap, bg=SIDEBAR)
        jump_frame.pack(fill="x", pady=(0, 10))
        tk.Label(jump_frame, text="Jump to Q#", bg=SIDEBAR, fg=TEXT, font=("Segoe UI", 9, "bold"), anchor="w").pack(
            fill="x"
        )
        row = tk.Frame(jump_frame, bg=SIDEBAR)
        row.pack(fill="x", pady=(4, 0))
        self.jump_entry = tk.Entry(row, textvariable=self.jump_var, font=("Segoe UI", 9))
        self.jump_entry.pack(side="left", fill="x", expand=True)
        tk.Button(
            row, text="Go", font=("Segoe UI", 8, "bold"), bg=BLUE, fg="white", bd=0, command=self.jump_to_question
        ).pack(side="left", padx=(6, 0))

        self.sidebar_stats = tk.Label(
            wrap, text="", bg=SIDEBAR, fg=MUTED, font=("Segoe UI", 9), anchor="w", justify="left"
        )
        self.sidebar_stats.pack(fill="x", pady=(0, 10))

        list_outer = tk.Frame(wrap, bg=BORDER)
        list_outer.pack(fill="both", expand=True)
        list_inner = tk.Frame(list_outer, bg=SIDEBAR)
        list_inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.question_list = tk.Listbox(
            list_inner,
            font=("Consolas", 9),
            selectmode="browse",
            activestyle="none",
            bd=0,
            relief="flat",
            highlightthickness=0,
            exportselection=False,
        )
        self.question_list.pack(side="left", fill="both", expand=True)
        self.question_list.bind("<<ListboxSelect>>", self.on_listbox_select)
        sb = tk.Scrollbar(list_inner, command=self.question_list.yview)
        sb.pack(side="right", fill="y")
        self.question_list.configure(yscrollcommand=sb.set)

    def on_filter_change(self, event=None):
        self.refresh_question_list()
        self.save_app_config()

    def _build_main(self):
        self.meta = tk.Frame(self.main, bg=BG)
        self.meta.pack(fill="x", padx=16, pady=(8, 6))
        self.meta_row = tk.Frame(self.meta, bg=BG)
        self.meta_row.pack(fill="x")
        self.meta_row.grid_columnconfigure(0, weight=0)
        self.meta_row.grid_columnconfigure(1, weight=1)
        self.meta_row.grid_columnconfigure(2, weight=0)
        self.progress_wrap = tk.Frame(self.meta_row, bg=BG, width=250, height=42)
        self.progress_wrap.grid(row=0, column=0, sticky="w")
        self.progress_wrap.grid_propagate(False)
        self.progress_label = tk.Label(
            self.progress_wrap, text="Progress: 0/0 (0%)", bg=BG, fg=MUTED, font=("Segoe UI", 8, "bold"), anchor="w"
        )
        self.progress_label.grid(row=0, column=0, sticky="w")
        self.progress_bar = ttk.Progressbar(
            self.progress_wrap,
            style="Blue.Horizontal.TProgressbar",
            orient="horizontal",
            length=220,
            mode="determinate",
            maximum=100,
        )
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.feedback_stage = tk.Frame(self.meta_row, bg=BG, width=360, height=74)
        self.feedback_stage.grid(row=0, column=1, sticky="ew", padx=(12, 12))
        self.feedback_stage.grid_propagate(False)
        self.top_feedback_label = tk.Label(
            self.feedback_stage,
            text="",
            bg="#ecf7ef",
            fg="#17643a",
            justify="center",
            anchor="center",
            padx=10,
            pady=3,
            font=("Segoe UI", 8, "bold"),
            relief="flat",
        )
        self.answer_result_overlay = tk.Label(
            self.feedback_stage,
            text="",
            bg="#ffffff",
            fg=BLUE,
            font=("Segoe UI", 11, "bold"),
            padx=18,
            pady=5,
            relief="solid",
            bd=1,
        )
        self.timer_label = tk.Label(
            self.meta_row, text="Time 00:00:00", bg=BG, fg=MUTED, font=("Segoe UI", 8), anchor="e"
        )
        self.timer_label.grid(row=0, column=2, sticky="e")

        self.card_outer = tk.Frame(self.main, bg=BORDER)
        self.card_outer.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        self.card = tk.Frame(self.card_outer, bg=CARD)
        self.card.pack(fill="both", expand=True, padx=1, pady=1)
        self.card_header_outer = tk.Frame(self.card, bg=BORDER)
        self.card_header_outer.pack(fill="x", side="top")
        self.card_header = tk.Frame(self.card_header_outer, bg=CARD, padx=16, pady=10)
        self.card_header.pack(fill="x", padx=1, pady=(1, 0))
        self.header_row = tk.Frame(self.card_header, bg=CARD)
        self.header_row.pack(fill="x")
        self.card_body = tk.Frame(self.card, bg=CARD)
        self.card_body.pack(fill="both", expand=True)
        self.content_canvas = tk.Canvas(self.card_body, bg=CARD, highlightthickness=0, bd=0)
        self.content_scroll = tk.Scrollbar(self.card_body, orient="vertical", command=self.content_canvas.yview)
        self.content_canvas.configure(yscrollcommand=self.content_scroll.set)
        self.content_scroll.pack(side="right", fill="y")
        self.content_canvas.pack(side="left", fill="both", expand=True)
        self.content_frame = tk.Frame(self.content_canvas, bg=CARD, padx=16, pady=12)
        self.canvas_window = self.content_canvas.create_window((0, 0), window=self.content_frame, anchor="nw")
        self.content_frame.bind("<Configure>", self._on_content_configure)
        self.content_canvas.bind("<Configure>", self._on_canvas_configure)
        self._bind_mousewheel()

        self.question_meta_label = tk.Label(
            self.header_row, text="", bg=CARD, fg=MUTED, font=QUESTION_META_FONT, anchor="w"
        )
        self.question_meta_label.pack(side="left")
        self.badge_wrap = tk.Frame(self.header_row, bg=CARD)
        self.badge_wrap.pack(side="right")
        self.meta_strip_label = tk.Label(
            self.badge_wrap, text="", bg="#f7f9fc", fg=DARK, font=QUESTION_META_STRIP_FONT, padx=10, pady=4
        )
        self.meta_strip_label.pack(side="right")
        self.issue_label = tk.Label(
            self.content_frame,
            text="",
            bg=LIGHT_YELLOW,
            fg=AMBER,
            justify="left",
            anchor="w",
            wraplength=960,
            padx=12,
            pady=8,
            font=QUESTION_META_FONT,
        )
        self.question_label = tk.Label(
            self.content_frame,
            text="",
            bg=CARD,
            fg=TEXT,
            justify="left",
            anchor="w",
            wraplength=960,
            font=QUESTION_PROMPT_FONT,
        )
        self.question_label.pack(fill="x", pady=(12, 14))

        self.choices_frame = tk.Frame(self.content_frame, bg=CARD)
        self.choices_frame.pack(fill="x")
        self.choice_rows = {}
        for letter in ["A", "B", "C", "D", "E", "F"]:
            row = ChoiceRow(self.choices_frame, letter, self.toggle_choice)
            row.pack(fill="x", pady=4)
            self.choice_rows[letter] = row

        self.review_panel = tk.Frame(self.content_frame, bg=CARD)
        self.status_label = tk.Label(
            self.review_panel, text="", bg=CARD, fg="white", font=QUESTION_STATUS_FONT, anchor="w", padx=12, pady=7
        )
        self.confidence_wrap = tk.Frame(self.review_panel, bg=CARD)
        self.confidence_label = tk.Label(
            self.confidence_wrap, text="Confidence", bg=CARD, fg=MUTED, font=("Segoe UI", 8, "bold")
        )
        self.confidence_label.pack(side="left", padx=(0, 8))
        self.confidence_buttons = {}
        for option in CONFIDENCE_OPTIONS:
            btn = tk.Button(
                self.confidence_wrap,
                text=option,
                font=("Segoe UI", 8, "bold"),
                bd=1,
                relief="solid",
                bg="#f7f9fc",
                fg=BLUE,
                padx=8,
                pady=3,
                command=lambda value=option: self.retag_current_answer_confidence(value),
            )
            btn.pack(side="left", padx=(0, 6))
            self.confidence_buttons[option] = btn
        self.super_confident_btn = tk.Button(
            self.confidence_wrap,
            text="Super confident",
            font=("Segoe UI", 8, "bold"),
            bd=1,
            relief="solid",
            bg="#f7f9fc",
            fg="#17643a",
            padx=8,
            pady=3,
            command=self.mark_current_question_super_confident,
        )
        self.super_confident_btn.pack(side="left", padx=(10, 0))
        self.answer_meta_label = tk.Label(
            self.review_panel,
            text="",
            bg="#fafbfd",
            fg=DARK,
            justify="left",
            anchor="w",
            wraplength=960,
            padx=12,
            pady=6,
            font=("Segoe UI", 8, "bold"),
        )

        self.card_action_outer = tk.Frame(self.card, bg="#cfd9e5")
        self.card_action_outer.pack(fill="x", side="bottom")
        self.card_action_panel = tk.Frame(self.card_action_outer, bg="#fbfcfe", padx=12, pady=6)
        self.card_action_panel.pack(fill="x", padx=1, pady=(1, 0))
        self.action_row = tk.Frame(self.card_action_panel, bg="#fbfcfe")
        self.action_row.pack(fill="x")
        self.action_left = tk.Frame(self.action_row, bg="#fbfcfe")
        self.action_left.pack(side="left")
        self.action_right = tk.Frame(self.action_row, bg="#fbfcfe")
        self.action_right.pack(side="right")
        self.submit_btn = tk.Button(
            self.action_left,
            text="SUBMIT ANSWER",
            font=("Segoe UI", 9, "bold"),
            bd=0,
            bg=GREEN,
            fg="white",
            padx=12,
            pady=6,
            command=self.submit_answer,
        )
        self.submit_btn.pack(side="left")
        self.flag_btn = tk.Button(
            self.action_left,
            text="FLAG",
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief="solid",
            bg="#f7f9fc",
            fg=BLUE,
            padx=12,
            pady=6,
            command=self.toggle_flag,
        )
        self.flag_btn.pack(side="left", padx=(8, 0))
        self.suspend_btn = tk.Button(
            self.action_left,
            text="SUSPEND",
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief="solid",
            bg="#f7f9fc",
            fg=RED,
            padx=12,
            pady=6,
            command=self.toggle_suspend,
        )
        self.suspend_btn.pack(side="left", padx=(8, 0))
        self.report_issue_btn = tk.Button(
            self.action_left,
            text="REPORT ISSUE",
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief="solid",
            bg="#f7f9fc",
            fg=AMBER,
            padx=12,
            pady=6,
            command=self.report_current_question_issue,
        )
        self.report_issue_btn.pack(side="left", padx=(8, 0))
        self.redo_btn = tk.Button(
            self.action_left,
            text="REDO QUESTION",
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief="solid",
            bg="#f7f9fc",
            fg=BLUE,
            padx=12,
            pady=6,
            command=self.redo_question,
        )
        self.redo_btn.pack(side="left", padx=(8, 0))
        self.next_unanswered_btn = tk.Button(
            self.action_left,
            text="NEXT UNANSWERED",
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief="solid",
            bg="#f7f9fc",
            fg=BLUE,
            padx=12,
            pady=6,
            command=self.next_unanswered,
        )
        self.next_unanswered_btn.pack(side="left", padx=(8, 0))
        self.super_confident_action_btn = tk.Button(
            self.action_left,
            text="SUPER CONFIDENT",
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief="solid",
            bg="#f7f9fc",
            fg="#17643a",
            padx=12,
            pady=6,
            command=self.mark_current_question_super_confident,
        )
        self.super_confident_action_btn.pack(side="left", padx=(8, 0))
        self.prev_btn = tk.Button(
            self.action_right,
            text="PREVIOUS",
            font=("Segoe UI", 8, "bold"),
            bd=1,
            relief="solid",
            bg="#f7f9fc",
            fg=BLUE,
            padx=12,
            pady=4,
            command=self.prev_question,
        )
        self.prev_btn.pack(side="left", padx=(0, 6))
        self.next_btn = tk.Button(
            self.action_right,
            text="NEXT",
            font=("Segoe UI", 8, "bold"),
            bd=1,
            relief="solid",
            bg=BLUE,
            fg="white",
            padx=12,
            pady=4,
            command=self.next_question,
        )
        self.next_btn.pack(side="left", padx=(0, 6))
        self.finish_btn = tk.Button(
            self.action_right,
            text="FINISH EXAM",
            font=("Segoe UI", 8, "bold"),
            bd=1,
            relief="solid",
            bg=AMBER,
            fg="white",
            padx=12,
            pady=4,
            command=self.finish_exam,
        )
        self.finish_btn.pack(side="left", padx=(0, 6))
        self.more_btn = tk.Menubutton(
            self.action_right,
            text="MORE",
            font=("Segoe UI", 8, "bold"),
            bd=1,
            relief="solid",
            bg="#f7f9fc",
            fg=BLUE,
            padx=12,
            pady=4,
        )
        self.more_btn.pack(side="left")
        self.more_menu = tk.Menu(self.more_btn, tearoff=0)
        self.more_btn.configure(menu=self.more_menu)
        self.action_hint = tk.Label(
            self.card_action_panel, text="", bg="#fbfcfe", fg=MUTED, font=("Segoe UI", 8), anchor="w"
        )

        self.explanation_wrap = tk.Frame(self.content_frame, bg=CARD)
        self.general_header = tk.Frame(self.explanation_wrap, bg=CARD)
        self.general_header.pack(fill="x", pady=(4, 6))
        self.general_heading = tk.Label(
            self.general_header, text="General explanation", bg=CARD, fg=TEXT, anchor="w", font=QUESTION_STATUS_FONT
        )
        self.general_heading.pack(side="left")
        self.recall_prompt_wrap = tk.Frame(self.explanation_wrap, bg="#fdf6ea")
        self.recall_prompt_label = tk.Label(
            self.recall_prompt_wrap,
            text="Recall mode: explain the answer to yourself before revealing the explanation.",
            bg="#fdf6ea",
            fg=DARK,
            justify="left",
            anchor="w",
            wraplength=940,
            padx=12,
            pady=10,
            font=("Segoe UI", 9, "bold"),
        )
        self.recall_prompt_label.pack(side="left", fill="x", expand=True)
        self.recall_done_btn = tk.Button(
            self.recall_prompt_wrap,
            text="SHOW EXPLANATION",
            font=("Segoe UI", 8, "bold"),
            bd=1,
            relief="solid",
            bg="#f7f9fc",
            fg=BLUE,
            padx=10,
            pady=4,
            command=self.complete_explanation_recall,
        )
        self.recall_done_btn.pack(side="right", padx=10, pady=10)
        self.general_card = tk.Label(
            self.explanation_wrap,
            text="",
            bg=LIGHT_BLUE,
            fg=TEXT,
            justify="left",
            anchor="w",
            wraplength=960,
            padx=12,
            pady=8,
            font=QUESTION_EXPLANATION_FONT,
        )

        self.footer = tk.Frame(self.main, bg=BG)
        self.footer.pack(fill="x", padx=16, pady=(0, 8))
        self.footer_info = tk.Frame(self.footer, bg=BG)
        self.footer_info.pack(fill="x")
        self.question_count = tk.Label(
            self.footer_info,
            text="QUESTION 1 of 1",
            bg=BG,
            fg="#3d3d3d",
            justify="left",
            anchor="w",
            font=("Segoe UI", 8, "bold"),
        )
        self.question_count.pack(fill="x")
        self.score_label = tk.Label(
            self.footer_info, text="", bg=BG, fg=MUTED, justify="left", anchor="w", font=("Segoe UI", 8)
        )
        self.session_label = tk.Label(
            self.footer_info,
            text="Session file: not saved yet",
            bg=BG,
            fg=MUTED,
            justify="left",
            anchor="w",
            font=("Segoe UI", 8),
        )
        self.checkpoint_label = tk.Label(
            self.footer_info, text="", bg=BG, fg=AMBER, justify="left", anchor="w", font=("Segoe UI", 8, "bold")
        )
        self.reward_banner_label = tk.Label(
            self.footer_info, text="", bg=BG, fg=GREEN, justify="left", anchor="w", font=("Segoe UI", 8, "bold")
        )
        self.loot_card = tk.Frame(self.footer_info, bg="#fff8df", bd=1, relief="solid")
        self.loot_title_label = tk.Label(
            self.loot_card, text="", bg="#fff8df", fg=AMBER, justify="left", anchor="w", font=("Segoe UI", 9, "bold")
        )
        self.loot_title_label.pack(fill="x", padx=10, pady=(7, 2))
        self.loot_stats_label = tk.Label(
            self.loot_card, text="", bg="#fff8df", fg=TEXT, justify="left", anchor="w", font=("Segoe UI", 8, "bold")
        )
        self.loot_stats_label.pack(fill="x", padx=10, pady=(0, 2))
        self.loot_detail_label = tk.Label(
            self.loot_card,
            text="",
            bg="#fff8df",
            fg=MUTED,
            justify="left",
            anchor="w",
            font=("Segoe UI", 8),
            wraplength=980,
        )
        self.loot_detail_label.pack(fill="x", padx=10, pady=(0, 7))
        self.gamef = tk.Frame(self.footer, bg="#f7f9fc", bd=1, relief="solid", highlightthickness=0)
        self.gamef.pack(fill="x", pady=(4, 0))
        game_top = tk.Frame(self.gamef, bg="#f7f9fc", padx=8, pady=4)
        game_top.pack(fill="x")
        self.study_hud_label = tk.Label(
            game_top,
            text="Study HUD: ready",
            bg="#f7f9fc",
            fg=DARK,
            justify="left",
            anchor="w",
            font=("Segoe UI", 8, "bold"),
        )
        self.study_hud_label.pack(side="left", fill="x", expand=True)

    def _bind_hotkeys(self):
        for ch in "abcdef":
            letter = ch.upper()
            self.root.bind(f"<KeyPress-{ch}>", lambda _event, answer_letter=letter: self.toggle_choice(answer_letter))
        self.root.bind("<Left>", lambda e: self.prev_question())
        self.root.bind("<Right>", lambda e: self.next_question())
        self.root.bind("<Return>", lambda e: self.handle_return_key())
        self.root.bind("<KeyPress-n>", lambda e: self.next_question())
        self.root.bind("<KeyPress-u>", lambda e: self.next_unanswered())
        self.root.bind("<Control-f>", lambda e: self.toggle_flag())

    def show_shortcuts(self):
        messagebox.showinfo(
            "Keyboard Shortcuts",
            "A-F: choose answer\n"
            "Enter: submit multi-select answer\n"
            "Left / Right: previous / next\n"
            "N: next question\n"
            "U: next unanswered\n"
            "Ctrl+F: flag or unflag",
        )

    def show_about(self):
        bank_path = self.bank_path if self.bank_path else DEFAULT_BANK
        progress_path = self.progress_path if self.progress_path else "not loaded"
        session_path = self.session_path if self.session_path else "not loaded"
        messagebox.showinfo(
            "About / System Info",
            f"{APP_NAME}\n"
            f"Version {APP_VERSION}\n\n"
            f"App folder:\n{APP_DIR}\n\n"
            f"User data:\n{USER_DATA_DIR}\n\n"
            f"Bank:\n{bank_path}\n\n"
            f"Progress:\n{progress_path}\n\n"
            f"Session:\n{session_path}\n\n"
            f"Log:\n{LOG_PATH}",
        )

    def _load_initial_bank(self):
        if self.bank_path and self.bank_path.exists():
            self.load_from_path(self.bank_path)
        else:
            messagebox.showerror("Missing file", "No default question bank was found next to the application.")

    def open_bank(self):
        path = filedialog.askopenfilename(
            title="Open Question Bank JSON", filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if path:
            self.load_from_path(Path(path))

    def reload_bank(self):
        if self.bank_path:
            self.load_from_path(self.bank_path)

    def _question_key(self, q):
        return question_key(q)

    def _progress_questions(self) -> ProgressQuestionMap:
        questions = self.progress_data.setdefault("questions", {})
        if not isinstance(questions, dict):
            questions = {}
            self.progress_data["questions"] = questions
        if questions is not getattr(self, "_normalized_progress_questions_ref", None):
            normalized = {str(key): normalize_progress_record(record) for key, record in questions.items()}
            questions.clear()
            questions.update(normalized)
            self._normalized_progress_questions_ref = questions
        return cast(ProgressQuestionMap, questions)

    def _progress_history(self) -> list[QuestionHistoryEvent]:
        history = self.progress_data.setdefault("history", [])
        if not isinstance(history, list):
            history = []
            self.progress_data["history"] = history
        return cast(list[QuestionHistoryEvent], history)

    def _progress_meta(self) -> ProgressMeta:
        meta = normalize_progress_meta(self.progress_data.setdefault("meta", {}))
        self.progress_data["meta"] = meta
        return meta

    def _progress_snapshot_payload(self):
        return {
            "questions": self._progress_questions(),
            "history": self._progress_history(),
            "meta": self._progress_meta(),
        }

    def _issue_reports(self) -> list[IssueReport]:
        return self._progress_meta()["issue_reports"]

    def _open_issue_reports_for_question(self, qnum):
        try:
            target_qnum = int(qnum or 0)
        except (TypeError, ValueError):
            return []
        return [
            report
            for report in self._issue_reports()
            if str(report.get("status") or "open") == "open"
            and str(report.get("question_number", "")).isdigit()
            and int(report.get("question_number", 0)) == target_qnum
        ]

    def question_has_open_issue_report(self, q):
        return bool(self._open_issue_reports_for_question(q.get("question_number")))

    def question_has_any_issue(self, q):
        return bool(q.get("flagged_issues")) or self.question_has_open_issue_report(q)

    def question_issue_notes(self, q):
        notes = list(q.get("flagged_issues", []))
        for report in self._open_issue_reports_for_question(q.get("question_number")):
            stamp = str(report.get("reported_at") or "").replace("T", " ")[:16]
            if report.get("exclude_from_scoring"):
                notes.append(
                    f"User-reported issue queued{f' on {stamp}' if stamp else ''}. Excluded from future study sets until reviewed."
                )
            else:
                notes.append(f"User-reported issue queued{f' on {stamp}' if stamp else ''}.")
        return notes

    def set_question_suspended_state(self, qnum, suspended):
        temp_q = {"question_number": qnum}
        rec = self._progress_record(temp_q, create=True)
        rec = set_progress_suspended(rec, suspended)
        self._progress_questions()[self._question_key(temp_q)] = rec
        self.set_suspended_by_question_number(qnum, suspended)
        if self.questions:
            current = self.current_question()
            if current and current.get("question_number") == qnum:
                current["suspended"] = bool(suspended)

    def report_current_question_issue(self):
        if not self.questions:
            return
        q = self.current_question()
        if self.question_has_open_issue_report(q):
            self.open_issue_review_window()
            messagebox.showinfo("Report issue", "This question is already in the local review queue.")
            return
        exclude = messagebox.askyesno(
            "Report issue",
            "Add this question to the local review queue and exclude it from future study sets until reviewed?\n\nYes = report and exclude\nNo = report only",
        )
        entry = issue_report_from_question(q, exclude_from_scoring=bool(exclude), reported_at=now_iso())
        self._issue_reports().append(entry)
        q["flagged"] = True
        self.update_progress_for_flag(q)
        if exclude:
            q["suspended"] = True
            self.update_progress_for_suspended(q)
        self.last_question_list_signature = None
        self.refresh_issue_review_window()
        self.schedule_session_save()
        self._render_current_view(save_session=False)
        self.checkpoint_label.configure(text=("Issue reported and excluded." if exclude else "Issue reported."))

    def _selected_issue_report_index(self):
        widgets = getattr(self, "issue_review_widgets", {})
        tree = widgets.get("tree")
        if not tree:
            return None
        selection = tree.selection()
        if not selection:
            return None
        try:
            return int(selection[0])
        except (TypeError, ValueError):
            return None

    def _resolve_issue_report(self, restore_scoring=True):
        idx = self._selected_issue_report_index()
        if idx is None:
            return
        reports = self._issue_reports()
        if idx < 0 or idx >= len(reports):
            return
        report = reports[idx]
        report["status"] = "reviewed"
        report["reviewed_at"] = now_iso()
        report["restored_scoring"] = bool(restore_scoring)
        qnum = report.get("question_number")
        if restore_scoring and report.get("exclude_from_scoring"):
            self.set_question_suspended_state(qnum, False)
        self.save_progress()
        self.last_question_list_signature = None
        self.refresh_issue_review_window()
        self.render_question()

    def open_issue_review_window(self):
        if self.issue_review_window and self.issue_review_window.winfo_exists():
            self.issue_review_window.deiconify()
            self.issue_review_window.lift()
            self.refresh_issue_review_window()
            return
        win = tk.Toplevel(self.root)
        win.title("Reported Issues")
        win.geometry("940x560")
        win.configure(bg=BG)
        win.protocol("WM_DELETE_WINDOW", self.close_issue_review_window)
        self.issue_review_window = win

        wrap = tk.Frame(win, bg=BG, padx=12, pady=12)
        wrap.pack(fill="both", expand=True)
        summary = tk.Label(wrap, text="", bg=BG, fg=DARK, anchor="w", justify="left", font=("Segoe UI", 9, "bold"))
        summary.pack(fill="x", pady=(0, 8))
        tree = ttk.Treeview(wrap, columns=("qnum", "page", "state", "exclude", "reported"), show="headings", height=12)
        tree.heading("qnum", text="Q#")
        tree.heading("page", text="Page")
        tree.heading("state", text="State")
        tree.heading("exclude", text="Excluded")
        tree.heading("reported", text="Reported")
        tree.column("qnum", width=70, anchor="center")
        tree.column("page", width=80, anchor="center")
        tree.column("state", width=100, anchor="center")
        tree.column("exclude", width=90, anchor="center")
        tree.column("reported", width=150, anchor="w")
        tree.pack(fill="both", expand=True)
        tree.bind("<<TreeviewSelect>>", self._on_issue_review_select)

        detail = tk.Label(
            wrap,
            text="",
            bg=LIGHT_BLUE,
            fg=TEXT,
            justify="left",
            anchor="w",
            wraplength=860,
            padx=12,
            pady=10,
            font=("Segoe UI", 9),
        )
        detail.pack(fill="x", pady=(10, 8))

        actions = tk.Frame(wrap, bg=BG)
        actions.pack(fill="x")
        tk.Button(
            actions,
            text="Resolve + Restore",
            font=("Segoe UI", 8, "bold"),
            bd=1,
            relief="solid",
            bg="#f7f9fc",
            fg=BLUE,
            padx=10,
            pady=4,
            command=lambda: self._resolve_issue_report(True),
        ).pack(side="left")
        tk.Button(
            actions,
            text="Resolve Only",
            font=("Segoe UI", 8, "bold"),
            bd=1,
            relief="solid",
            bg="#f7f9fc",
            fg=BLUE,
            padx=10,
            pady=4,
            command=lambda: self._resolve_issue_report(False),
        ).pack(side="left", padx=(8, 0))

        self.issue_review_widgets = cast(
            IssueReviewWidgetRegistry,
            {
                "summary": summary,
                "tree": tree,
                "detail": detail,
            },
        )
        self.refresh_issue_review_window()

    def close_issue_review_window(self):
        if self.issue_review_window and self.issue_review_window.winfo_exists():
            self.issue_review_window.destroy()
        self.issue_review_window = None
        self.issue_review_widgets = cast(IssueReviewWidgetRegistry, {})

    def _on_issue_review_select(self, _event=None):
        if not self.issue_review_window or not self.issue_review_window.winfo_exists():
            return
        self._render_issue_review_detail()

    def refresh_issue_review_window(self):
        if not self.issue_review_window or not self.issue_review_window.winfo_exists():
            return
        widgets = self.issue_review_widgets
        reports = list(self._issue_reports())
        open_count = sum(1 for report in reports if str(report.get("status") or "open") == "open")
        excluded_count = sum(1 for report in reports if report.get("exclude_from_scoring"))
        widgets["summary"].configure(text=f"Reports: {len(reports)}   Open: {open_count}   Excluded: {excluded_count}")
        tree = widgets["tree"]
        selected = tree.selection()
        selected_iid = selected[0] if selected else None
        tree.delete(*tree.get_children())
        for idx, report in enumerate(reports):
            tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    report.get("question_number", ""),
                    report.get("source_page", ""),
                    str(report.get("status") or "open").title(),
                    "Yes" if report.get("exclude_from_scoring") else "No",
                    str(report.get("reported_at") or "").replace("T", " ")[:16],
                ),
            )
        if selected_iid and tree.exists(selected_iid):
            tree.selection_set(selected_iid)
        elif tree.get_children():
            tree.selection_set(tree.get_children()[0])
        self._render_issue_review_detail(reports)

    def _render_issue_review_detail(self, reports=None):
        if not self.issue_review_window or not self.issue_review_window.winfo_exists():
            return
        widgets = self.issue_review_widgets
        reports = list(reports if reports is not None else self._issue_reports())
        idx = self._selected_issue_report_index()
        if idx is None or idx >= len(reports):
            widgets["detail"].configure(text="No issue report selected.")
            return
        report = reports[idx]
        details = [
            f"Q{report.get('question_number', '')}  Page {report.get('source_page', '')}  Domain: {report.get('domain', '')}",
            "",
            str(report.get("prompt", "")).strip() or "No prompt preview captured.",
        ]
        for note in report.get("source_notes", []) or []:
            details.append("")
            details.append(f"Source note: {note}")
        if report.get("reviewed_at"):
            details.append("")
            details.append(f"Reviewed: {str(report.get('reviewed_at')).replace('T', ' ')[:16]}")
        widgets["detail"].configure(text="\n".join(details))

    def _screenshot_review_questions(self):
        return [
            q
            for q in self.master_questions
            if q.get("import_status") == "screenshot_review_needed"
            or (q.get("suspended") and "screenshot" in str(q.get("source_label", "")).lower())
        ]

    def _selected_screenshot_review_qnum(self):
        widgets = getattr(self, "screenshot_review_widgets", {})
        tree = widgets.get("tree")
        if not tree:
            return None
        selection = tree.selection()
        if not selection:
            return None
        try:
            return int(selection[0])
        except (TypeError, ValueError):
            return None

    def _screenshot_review_question_by_qnum(self, qnum):
        try:
            target = int(qnum or 0)
        except (TypeError, ValueError):
            return None
        for question in self.master_questions:
            if int(question.get("question_number") or 0) == target:
                return question
        return None

    def _update_bank_question_fields(self, qnum, updates):
        if not self.bank_path:
            messagebox.showerror("Screenshot Review", "No active bank file is loaded.")
            return False
        try:
            raw = json.loads(self.bank_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logging.exception("Unable to read bank for screenshot review update.")
            messagebox.showerror("Screenshot Review", f"Could not read the bank file:\n{exc}")
            return False
        changed = False
        for question in raw.get("questions", []):
            if int(question.get("question_number") or 0) == int(qnum or 0):
                question.update(copy.deepcopy(updates))
                changed = True
                break
        if not changed:
            messagebox.showerror("Screenshot Review", f"Could not find Q{qnum} in the bank file.")
            return False
        try:
            safe_write_json(self.bank_path, raw)
        except Exception as exc:
            logging.exception("Unable to write bank for screenshot review update.")
            messagebox.showerror("Screenshot Review", f"Could not save the bank file:\n{exc}")
            return False
        if self.data:
            for question in self.data.get("questions", []):
                if int(question.get("question_number") or 0) == int(qnum or 0):
                    question.update(copy.deepcopy(updates))
                    break
        for collection in (self.master_questions, self.questions):
            for question in collection:
                if int(question.get("question_number") or 0) == int(qnum or 0):
                    question.update(copy.deepcopy(updates))
        return True

    def open_screenshot_review_window(self):
        if self.screenshot_review_window and self.screenshot_review_window.winfo_exists():
            self.screenshot_review_window.deiconify()
            self.screenshot_review_window.lift()
            self.refresh_screenshot_review_window()
            return
        win = tk.Toplevel(self.root)
        win.title("Screenshot Review")
        win.geometry("1120x760")
        win.configure(bg=BG)
        win.protocol("WM_DELETE_WINDOW", self.close_screenshot_review_window)
        self.screenshot_review_window = win

        wrap = tk.Frame(win, bg=BG, padx=12, pady=12)
        wrap.pack(fill="both", expand=True)
        summary = tk.Label(wrap, text="", bg=BG, fg=DARK, anchor="w", justify="left", font=("Segoe UI", 9, "bold"))
        summary.pack(fill="x", pady=(0, 8))
        body = tk.Frame(wrap, bg=BG)
        body.pack(fill="both", expand=True)

        tree = ttk.Treeview(
            body,
            columns=("qnum", "source", "image", "status"),
            show="headings",
            height=18,
        )
        tree.heading("qnum", text="Q#")
        tree.heading("source", text="Source")
        tree.heading("image", text="Image")
        tree.heading("status", text="Status")
        tree.column("qnum", width=70, anchor="center")
        tree.column("source", width=170, anchor="w")
        tree.column("image", width=280, anchor="w")
        tree.column("status", width=110, anchor="center")
        tree.pack(side="left", fill="both", expand=False)
        tree.bind("<<TreeviewSelect>>", self._on_screenshot_review_select)

        editor = tk.Frame(body, bg=BG, padx=12)
        editor.pack(side="left", fill="both", expand=True)
        detail = tk.Label(
            editor,
            text="Select a screenshot review item.",
            bg=LIGHT_BLUE,
            fg=TEXT,
            justify="left",
            anchor="w",
            wraplength=720,
            padx=10,
            pady=8,
            font=("Segoe UI", 9),
        )
        detail.pack(fill="x", pady=(0, 8))

        tk.Label(editor, text="Prompt", bg=BG, fg=DARK, anchor="w", font=("Segoe UI", 8, "bold")).pack(fill="x")
        prompt = tk.Text(editor, height=4, wrap="word", font=("Segoe UI", 9))
        prompt.pack(fill="x", pady=(2, 8))
        choice_vars = {letter: tk.StringVar() for letter in "ABCD"}
        for letter in "ABCD":
            row = tk.Frame(editor, bg=BG)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=f"{letter}", bg=BG, fg=BLUE, width=3, font=("Segoe UI", 8, "bold")).pack(side="left")
            tk.Entry(row, textvariable=choice_vars[letter], font=("Segoe UI", 9)).pack(
                side="left", fill="x", expand=True
            )
        key_row = tk.Frame(editor, bg=BG)
        key_row.pack(fill="x", pady=(8, 8))
        tk.Label(key_row, text="Correct", bg=BG, fg=DARK, font=("Segoe UI", 8, "bold")).pack(side="left")
        correct_var = tk.StringVar(value="A")
        ttk.Combobox(key_row, values=["A", "B", "C", "D"], textvariable=correct_var, width=6, state="readonly").pack(
            side="left", padx=(8, 0)
        )

        tk.Label(editor, text="Explanation", bg=BG, fg=DARK, anchor="w", font=("Segoe UI", 8, "bold")).pack(fill="x")
        explanation = tk.Text(editor, height=7, wrap="word", font=("Segoe UI", 9))
        explanation.pack(fill="both", expand=True, pady=(2, 8))

        actions = tk.Frame(editor, bg=BG)
        actions.pack(fill="x")
        tk.Button(
            actions,
            text="Open Source Image",
            font=("Segoe UI", 8, "bold"),
            bd=1,
            relief="solid",
            bg="#f7f9fc",
            fg=BLUE,
            padx=10,
            pady=4,
            command=self.open_selected_screenshot_source_image,
        ).pack(side="left")
        tk.Button(
            actions,
            text="Save + Enable",
            font=("Segoe UI", 8, "bold"),
            bd=1,
            relief="solid",
            bg="#e8f5ee",
            fg=GREEN,
            padx=10,
            pady=4,
            command=self.save_selected_screenshot_review_item,
        ).pack(side="left", padx=(8, 0))
        tk.Button(
            actions,
            text="Keep Quarantined",
            font=("Segoe UI", 8, "bold"),
            bd=1,
            relief="solid",
            bg="#f7f9fc",
            fg=MUTED,
            padx=10,
            pady=4,
            command=self.refresh_screenshot_review_window,
        ).pack(side="left", padx=(8, 0))

        self.screenshot_review_widgets = cast(
            ScreenshotReviewWidgetRegistry,
            {
                "summary": summary,
                "tree": tree,
                "detail": detail,
                "prompt": prompt,
                "choices": choice_vars,
                "correct": correct_var,
                "explanation": explanation,
            },
        )
        self.refresh_screenshot_review_window()

    def close_screenshot_review_window(self):
        if self.screenshot_review_window and self.screenshot_review_window.winfo_exists():
            self.screenshot_review_window.destroy()
        self.screenshot_review_window = None
        self.screenshot_review_widgets = cast(ScreenshotReviewWidgetRegistry, {})

    def _on_screenshot_review_select(self, _event=None):
        self._render_screenshot_review_detail()

    def refresh_screenshot_review_window(self):
        if not self.screenshot_review_window or not self.screenshot_review_window.winfo_exists():
            return
        widgets = self.screenshot_review_widgets
        review_items = self._screenshot_review_questions()
        widgets["summary"].configure(
            text=f"Screenshot review queue: {len(review_items)} quarantined items. Save + Enable only after verifying against the source image."
        )
        tree = widgets["tree"]
        selected = tree.selection()
        selected_iid = selected[0] if selected else None
        tree.delete(*tree.get_children())
        for question in review_items:
            qnum = int(question.get("question_number") or 0)
            tree.insert(
                "",
                "end",
                iid=str(qnum),
                values=(
                    qnum,
                    question.get("source_label", ""),
                    question.get("source_image", ""),
                    "Quarantined" if question.get("suspended") else "Review",
                ),
            )
        if selected_iid and tree.exists(selected_iid):
            tree.selection_set(selected_iid)
        elif tree.get_children():
            tree.selection_set(tree.get_children()[0])
        self._render_screenshot_review_detail()

    def _render_screenshot_review_detail(self):
        if not self.screenshot_review_window or not self.screenshot_review_window.winfo_exists():
            return
        widgets = self.screenshot_review_widgets
        qnum = self._selected_screenshot_review_qnum()
        question = self._screenshot_review_question_by_qnum(qnum)
        if not question:
            widgets["detail"].configure(text="No screenshot review item selected.")
            return
        widgets["detail"].configure(
            text=(
                f"Q{question.get('question_number')}  {question.get('source_label', '')}\n"
                f"Source image: {question.get('source_image', '')}\n"
                "Transcribe/fix the fields below, choose the verified correct answer, then Save + Enable."
            )
        )
        widgets["prompt"].delete("1.0", tk.END)
        widgets["prompt"].insert("1.0", str(question.get("prompt") or ""))
        choice_vars = widgets["choices"]
        for letter in "ABCD":
            choice_vars[letter].set(str((question.get("choices") or {}).get(letter, "")))
        correct = next(iter(question.get("correct") or ["A"]), "A")
        widgets["correct"].set(str(correct).strip().upper() if str(correct).strip().upper() in "ABCD" else "A")
        widgets["explanation"].delete("1.0", tk.END)
        widgets["explanation"].insert("1.0", str(question.get("general_explanation") or ""))

    def open_selected_screenshot_source_image(self):
        qnum = self._selected_screenshot_review_qnum()
        question = self._screenshot_review_question_by_qnum(qnum)
        if not question:
            return
        path = Path(str(question.get("source_image_path") or ""))
        if not path.exists():
            messagebox.showwarning("Screenshot Review", f"Source image was not found:\n{path}")
            return
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception as exc:
            messagebox.showerror("Screenshot Review", f"Could not open image:\n{exc}")

    def save_selected_screenshot_review_item(self):
        qnum = self._selected_screenshot_review_qnum()
        question = self._screenshot_review_question_by_qnum(qnum)
        if not question:
            return
        widgets = self.screenshot_review_widgets
        prompt = widgets["prompt"].get("1.0", tk.END).strip()
        choices = {letter: widgets["choices"][letter].get().strip() for letter in "ABCD"}
        correct = widgets["correct"].get().strip().upper()
        explanation = widgets["explanation"].get("1.0", tk.END).strip()
        missing = [
            label for label, value in [("prompt", prompt), ("explanation", explanation), *choices.items()] if not value
        ]
        if missing:
            messagebox.showwarning("Screenshot Review", f"Fill these before enabling: {', '.join(missing)}")
            return
        if correct not in choices:
            messagebox.showwarning("Screenshot Review", "Pick a valid correct answer: A, B, C, or D.")
            return
        updates = {
            "prompt": prompt,
            "choices": choices,
            "correct": [correct],
            "question_type": "single",
            "general_explanation": explanation,
            "choice_explanations": {
                letter: (
                    "Verified correct answer from screenshot review."
                    if letter == correct
                    else f"Not keyed as correct in the verified screenshot. Compare against: {correct}."
                )
                for letter in "ABCD"
            },
            "flagged_issues": [],
            "suspended": False,
            "import_status": "screenshot_verified",
            "reviewed_at": now_iso(),
        }
        if not self._update_bank_question_fields(qnum, updates):
            return
        self.set_question_suspended_state(qnum, False)
        self.invalidate_learning_state(prewarm=True, prewarm_delay_ms=0)
        self.save_progress()
        self.schedule_session_save()
        self.last_question_list_signature = None
        self.refresh_question_list()
        self.refresh_screenshot_review_window()
        self.checkpoint_label.configure(text=f"Q{qnum} verified and enabled for practice.")

    def _progress_record(self, q, create=False) -> ProgressRecord | None:
        key = self._question_key(q)
        records = self._progress_questions()
        if create and key not in records:
            records[key] = default_progress_record()
        record = records.get(key)
        if record is None:
            return None
        return cast(ProgressRecord, record)

    def _show_bad_json_warning(self, label, path, backup, err):
        messagebox.showwarning(
            f"{label} reset",
            f"{label} file could not be read and was moved aside.\n\n"
            f"Original: {path.name}\n"
            f"Backup: {backup.name}\n\n"
            f"The app will start fresh for that file.\n\n{err}",
        )

    def backup_file_for_progress(self, suffix="manual"):
        if not self.progress_path:
            return None
        return self.persistence.progress_backup_path(self.progress_path, suffix=suffix)

    def auto_backup_progress(self):
        backup = self.persistence.backup_progress_file(self.progress_path, suffix="auto_backup")
        if backup is not None:
            logging.info("Auto progress backup saved: %s", backup)

    def backup_progress_manual(self):
        if not self.progress_path:
            messagebox.showinfo("Progress backup", "Open a question bank first.")
            return
        self.save_progress()
        default = self.backup_file_for_progress("backup")
        path = filedialog.asksaveasfilename(
            title="Backup Progress",
            defaultextension=".json",
            initialfile=default.name,
            initialdir=str(default.parent),
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        self.persistence.backup_progress_file(self.progress_path, suffix="manual", destination=Path(path))
        logging.info("Manual progress backup saved: %s", path)
        messagebox.showinfo("Progress backup", f"Saved progress backup to:\n{path}")

    def restore_progress_manual(self):
        if not self.progress_path:
            messagebox.showinfo("Restore progress", "Open a question bank first.")
            return
        path = filedialog.askopenfilename(
            title="Restore Progress JSON", filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if not path:
            return
        restore_path = Path(path)
        data, backup, err = self.persistence.load_json_with_backup(restore_path)
        if err:
            logging.warning("Restore progress source was unreadable: %s", restore_path)
            self._show_bad_json_warning("Restore progress", restore_path, backup, err)
            return
        if not isinstance(data, dict) or not isinstance(data.get("questions"), dict):
            messagebox.showerror("Restore progress", "That file is not a valid progress JSON file.")
            return
        if self.progress_path.exists():
            self.auto_backup_progress()
        self.persistence.copy_file(restore_path, self.progress_path, label="restored progress")
        self.load_progress_if_present()
        self.master_questions = self._clone_questions(self.data["questions"])
        self._reset_runtime_question_state(self.master_questions)
        self._rebuild_followup_candidate_index()
        self.start_session_from_pool(
            self.master_questions,
            mode=MODE_PRACTICE,
            count="All visible",
            randomize=False,
            reset_clock=False,
            preserve_if_saved=True,
            source_label="Full bank",
        )
        logging.info("Progress restored from: %s", restore_path)
        messagebox.showinfo("Restore progress", "Progress was restored and the bank was refreshed.")

    def load_progress_if_present(self):
        self.progress_data = blank_progress(self.bank_path.name if self.bank_path else "", app_version=APP_VERSION)
        self.last_progress_snapshot = json.dumps(
            self._progress_snapshot_payload(), sort_keys=True, separators=(",", ":")
        )
        if not self.progress_path or not self.progress_path.exists():
            if self.bank_path and self.progress_path:
                self.migrate_runtime_file(
                    self.legacy_progress_file_for_bank(self.bank_path), self.progress_path, "progress"
                )
            if not self.progress_path or not self.progress_path.exists():
                return
        self.auto_backup_progress()
        data, backup, err = self.persistence.load_json_with_backup(self.progress_path)
        if err:
            logging.warning("Progress file reset after read failure: %s", self.progress_path)
            self._show_bad_json_warning("Progress", self.progress_path, backup, err)
            return
        if not isinstance(data, dict):
            return
        data.setdefault("version", PROGRESS_VERSION)
        data.setdefault("app_version", APP_VERSION)
        data.setdefault("bank_file", self.bank_path.name if self.bank_path else "")
        data.setdefault("created_at", now_iso())
        data.setdefault("updated_at", data.get("created_at") or now_iso())
        if not isinstance(data.get("questions"), dict):
            data["questions"] = {}
        if not isinstance(data.get("history"), list):
            data["history"] = []
        if not isinstance(data.get("meta"), dict):
            data["meta"] = {}
        self.progress_data = data
        self._progress_meta()
        self.normalize_progress_repair_state()
        self.last_progress_snapshot = json.dumps(
            self._progress_snapshot_payload(), sort_keys=True, separators=(",", ":")
        )
        logging.info("Loaded progress file: %s", self.progress_path)

    def save_progress(self):
        if not self.progress_path:
            return
        self.save_queue.cancel("progress")
        snapshot = json.dumps(self._progress_snapshot_payload(), sort_keys=True, separators=(",", ":"))
        if snapshot == self.last_progress_snapshot:
            return
        self.progress_data.setdefault("version", PROGRESS_VERSION)
        self.progress_data["app_version"] = APP_VERSION
        self.progress_data.setdefault("bank_file", self.bank_path.name if self.bank_path else "")
        self.progress_data.setdefault("created_at", now_iso())
        self.progress_data["updated_at"] = now_iso()
        self._progress_meta()
        self.persistence.write_json(self.progress_path, self.progress_data)
        self.last_progress_snapshot = snapshot

    def apply_progress_to_questions(self, questions):
        records = self._progress_questions()
        for q in questions:
            rec = records.get(self._question_key(q))
            if rec:
                q["flagged"] = bool(rec.get("flagged")) or bool(q.get("flagged"))
                q["suspended"] = bool(rec.get("suspended"))
                q["last_confidence"] = str(rec.get("last_confidence", "") or "")
                q["last_miss_reason"] = str(rec.get("last_miss_reason", "") or "")

    def set_flag_by_question_number(self, qnum, flagged):
        for collection in (self.master_questions, self.questions):
            for q in collection:
                if q.get("question_number") == qnum:
                    q["flagged"] = bool(flagged)

    def set_suspended_by_question_number(self, qnum, suspended):
        for collection in (self.master_questions, self.questions):
            for q in collection:
                if q.get("question_number") == qnum:
                    q["suspended"] = bool(suspended)

    def append_answer_history(self, q, is_correct, feedback):
        rec = self._progress_record(q, create=False) or {}
        selected_letters = list(q.get("selected", []))
        correct_letters = list(q.get("correct", []))
        prediction_fields = event_prediction_fields(q)
        event: QuestionHistoryEvent = {
            "at": now_iso(),
            "day": str(rec.get("last_seen") or ""),
            "question_number": int(q.get("question_number") or 0),
            "correct": bool(is_correct),
            "confidence": str((feedback or {}).get("confidence") or ""),
            "miss_reason": str((feedback or {}).get("miss_reason") or ""),
            "domain": q.get("domain") or "Unsorted",
            "topics": [str(topic).strip() for topic in q.get("topics", []) if str(topic).strip()],
            "objective_code": str(q.get("objective_code") or ""),
            "source_label": str(q.get("source_label") or q.get("source_name") or "Unknown source"),
            "mode": self.active_session_mode,
            "trap_words": self.question_trap_words(q),
            "selected": selected_letters,
            "correct_letters": correct_letters,
            "selected_texts": [
                str(q.get("choices", {}).get(letter, "")).strip()
                for letter in selected_letters
                if str(q.get("choices", {}).get(letter, "")).strip()
            ],
            "correct_texts": [
                str(q.get("choices", {}).get(letter, "")).strip()
                for letter in correct_letters
                if str(q.get("choices", {}).get(letter, "")).strip()
            ],
            "wrong_answer_family": "" if is_correct else self.classify_wrong_answer_family(q),
            "recall_failure": str(
                (feedback or {}).get("recall_failure") or self.classify_recall_failure(q, is_correct, feedback)
            ),
            "deciding_clue": str((feedback or {}).get("deciding_clue") or self.deciding_clue_for_question(q)),
            "response_seconds": float(
                (feedback or {}).get("effective_response_seconds", (feedback or {}).get("response_seconds")) or 0.0
            ),
            "raw_response_seconds": float((feedback or {}).get("raw_response_seconds") or 0.0),
            "effective_response_seconds": float(
                (feedback or {}).get("effective_response_seconds", (feedback or {}).get("response_seconds")) or 0.0
            ),
            "response_time_contaminated": bool((feedback or {}).get("response_time_contaminated")),
            "was_due": bool((feedback or {}).get("was_due")),
            "was_active_weak": bool((feedback or {}).get("was_active_weak")),
            "session_tag": str(q.get("session_tag") or ""),
            "smart_primary_role": str(q.get("smart_primary_role") or ""),
            "smart_selection_reasons": [str(value) for value in q.get("smart_selection_reasons", [])],
            "smart_utility": float(q.get("smart_utility", 0.0) or 0.0),
            "smart_policy_id": str(q.get("smart_policy_id") or prediction_fields.get("smart_policy_id") or ""),
            "smart_policy_version": str(
                q.get("smart_policy_version") or prediction_fields.get("smart_policy_version") or ""
            ),
            "smart_concept_key": str(q.get("smart_concept_key") or ""),
            "smart_root_cause": str(q.get("smart_root_cause") or ""),
            "smart_root_cause_confidence": float(q.get("smart_root_cause_confidence", 0.0) or 0.0),
            "smart_supporting_concepts": [str(value) for value in q.get("smart_supporting_concepts", [])],
            "smart_graph_version": str(q.get("smart_graph_version") or ""),
            "smart_information_value": float(q.get("smart_information_value", 0.0) or 0.0),
            "smart_information_breakdown": dict(q.get("smart_information_breakdown") or {}),
            "smart_question_quality_status": str(q.get("smart_question_quality_status") or ""),
            "smart_question_quality_confidence": float(q.get("smart_question_quality_confidence", 0.0) or 0.0),
            "smart_graph_bottleneck": float(q.get("smart_graph_bottleneck", 0.0) or 0.0),
            "repair_stage": str(q.get("repair_stage") or ""),
            "repair_concept_key": str(q.get("repair_concept_key") or ""),
            "event_id": str(prediction_fields.get("prediction_id") or "") + f":{now_iso()}",
            **prediction_fields,
        }
        append_progress_history(self.progress_data, event)

    def update_progress_for_answer(self, q, feedback=None):
        feedback = feedback or {}
        rec = self._progress_record(q, create=True)
        rec = update_progress_record(
            rec,
            q.get("selected", []),
            self._question_correct(q),
            confidence=feedback.get("confidence"),
            miss_reason=feedback.get("miss_reason"),
            effective_response_seconds=feedback.get("effective_response_seconds", feedback.get("response_seconds", 0.0)),
            session_tag=q.get("session_tag", ""),
            recall_failure=feedback.get("recall_failure", ""),
        )
        self._progress_questions()[self._question_key(q)] = rec
        q["last_confidence"] = str(rec.get("last_confidence", "") or "")
        q["last_miss_reason"] = str(rec.get("last_miss_reason", "") or "")
        self.append_answer_history(q, self._question_correct(q), feedback)
        self.invalidate_learning_state(prewarm=False)
        self.schedule_progress_save()

    def update_progress_for_flag(self, q):
        rec = self._progress_record(q, create=True)
        rec = set_progress_flag(rec, q.get("flagged", False))
        self._progress_questions()[self._question_key(q)] = rec
        self.set_flag_by_question_number(q.get("question_number"), q.get("flagged", False))
        self.invalidate_learning_state(prewarm=True, prewarm_delay_ms=900)
        self.schedule_progress_save()

    def update_progress_for_suspended(self, q):
        rec = self._progress_record(q, create=True)
        rec = set_progress_suspended(rec, q.get("suspended", False))
        self._progress_questions()[self._question_key(q)] = rec
        self.set_suspended_by_question_number(q.get("question_number"), q.get("suspended", False))
        self.invalidate_learning_state(prewarm=True, prewarm_delay_ms=900)
        self.schedule_progress_save()

    def progress_summary(self) -> ProgressSummary:
        records = self._progress_questions()
        cache_key = tuple(
            (
                key,
                int(rec.get("attempts", 0)),
                int(rec.get("correct_count", 0)),
                int(rec.get("wrong_count", 0)),
                int(rec.get("correct_streak", 0)),
                str(rec.get("next_review", "")),
                bool(rec.get("flagged")),
                bool(rec.get("suspended")),
                rec.get("last_correct"),
            )
            for key, rec in sorted(records.items())
        )
        if cache_key == self.progress_summary_cache_key and self.progress_summary_cache_payload is not None:
            return dict(self.progress_summary_cache_payload)
        active_records = [r for r in records.values() if not is_suspended(r)]
        attempted = sum(1 for r in active_records if int(r.get("attempts", 0)) > 0)
        due = sum(1 for r in active_records if is_review_due(r))
        flagged = sum(1 for r in active_records if r.get("flagged"))
        wrong = sum(1 for r in active_records if is_active_weak(r))
        recovered = sum(1 for r in active_records if is_ever_wrong(r) and not is_active_weak(r))
        ever_wrong = sum(1 for r in active_records if is_ever_wrong(r))
        mastered = sum(1 for r in active_records if int(r.get("correct_streak", 0)) >= 4 and not is_review_due(r))
        payload: ProgressSummary = {
            "attempted": attempted,
            "due": due,
            "flagged": flagged,
            "wrong": wrong,
            "recovered": recovered,
            "ever_wrong": ever_wrong,
            "mastered": mastered,
        }
        self.progress_summary_cache_key = cache_key
        self.progress_summary_cache_payload = dict(payload)
        return payload

    def clear_active_session(self, reset_clock=True):
        self.questions = []
        self.visible_indices = []
        self.index = 0
        self.active_source_label = ""
        self.session_path = None
        self.last_session_snapshot = None
        self.last_question_list_signature = None
        self.exam_reveal = True
        self.answer_order_epoch = 0
        self.unlocked_rewards = set()
        self.session_rewards = []
        self.current_quests = []
        self.quest_completion_keys = set()
        self.session_boss_markers = set()
        self.session_stealth_markers = set()
        self.session_combo_burst_markers = set()
        self.session_xp_gained = 0
        self.session_completion_signature = None
        self.last_session_summary = None
        self.pass_score_victory_unlocked = False
        self.clear_victory_animation()
        self.clear_study_hud_pulse()
        self.clear_answer_feedback_chip()
        self.clear_answer_result_overlay()
        self.active_question_started_qnum = None
        self.active_question_started_at = None
        self.session_answer_history = []
        self.rescue_domains_triggered = set()
        self.session_base_question_count = None
        self.session_question_limit = None
        self.session_restore_question_numbers = []
        self.current_builder_context_data = {}
        self.checkpoints_saved = set()
        self.last_checkpoint_notice = ""
        self.checkpoint_label.configure(text="")
        self.clear_reward_banner()
        self.clear_answer_toast()
        self.clear_session_loot_card()
        self.refresh_reward_badges()
        self.scroll_to_top_on_render = True
        if reset_clock:
            self.elapsed_base = 0
            self.clock_started_at = time.time()
        self.set_sidebar_visible(True)
        self.render_question()

    def question_trap_words(self, q):
        prompt = str((q or {}).get("prompt") or "")
        lowered = prompt.lower()
        hits = []
        for label, pattern in TRAP_WORD_PATTERNS:
            if re.search(pattern, lowered):
                hits.append(label)
        return hits

    def _tokenize_text(self, text):
        return {token for token in re.findall(r"[a-z0-9]+", str(text or "").lower()) if len(token) > 2}

    def classify_wrong_answer_family(self, q):
        if self._question_correct(q):
            return ""
        trap_words = self.question_trap_words(q)
        if any(word in trap_words for word in ("except", "not")):
            return "Qualifier / exception trap"
        if any(word in trap_words for word in ("best", "most", "least", "primary")):
            return "Technically true but not best"
        if any(word in trap_words for word in ("first", "next", "initial", "immediate")):
            return "Order-of-operations trap"
        selected_text = " ".join(str(q.get("choices", {}).get(letter, "")) for letter in q.get("selected", []))
        correct_text = " ".join(str(q.get("choices", {}).get(letter, "")) for letter in q.get("correct", []))
        selected_tokens = self._tokenize_text(selected_text)
        correct_tokens = self._tokenize_text(correct_text)
        if selected_tokens and correct_tokens:
            overlap = len(selected_tokens & correct_tokens) / max(len(selected_tokens | correct_tokens), 1)
            if overlap >= 0.35:
                return "Near-synonym / look-alike distractor"
        if selected_tokens & ABSOLUTE_DISTRACTOR_WORDS and not (correct_tokens & ABSOLUTE_DISTRACTOR_WORDS):
            return "Too-broad distractor"
        return "Plausible distractor"

    def slowdown_prompt_text(self, q):
        return ""

    def adaptive_explanation_text(self, q):
        rec = self._progress_record(q, create=False) or {}
        reason = str(q.get("last_miss_reason") or rec.get("last_miss_reason") or "").strip()
        confidence = str(q.get("last_confidence") or rec.get("last_confidence") or "").strip()
        selected = ", ".join(q.get("selected", [])) or "none"
        correct = ", ".join(q.get("correct", [])) or "none"
        if q.get("answered") and self._question_correct(q):
            if confidence == "Guessed":
                return f"Coaching note: treat this as fragile. You got it right while guessing, so restate why {correct} is correct before you move on."
            if confidence == "Unsure":
                return f"Coaching note: solidify the logic behind {correct}. You were unsure, so this is more review than mastery."
            return f"Coaching note: explain in one sentence why {correct} is right. That helps convert recall into mastery."
        if reason == "Did not know":
            return f"Coaching note: this is a knowledge-gap miss. Focus on the core concept behind {correct} before worrying about memorizing the letters."
        if reason == "Misread":
            return f"Coaching note: slow down on qualifier words and scope. Compare what you picked ({selected}) against what the question actually asked for ({correct})."
        if reason == "Narrowed to two":
            return f"Coaching note: compare the tempting wrong option ({selected}) directly against the keyed answer ({correct}) and name the deciding clue."
        if reason == "Changed answer":
            return f"Coaching note: audit why you moved off your first instinct. Look for the specific evidence that supports {correct} over {selected}."
        return f"Coaching note: restate why {correct} wins and why {selected} misses. That contrast is where retention usually sticks."

    def question_volatility(self, q):
        qnum = int((q or {}).get("question_number") or 0)
        events = [event for event in self._progress_history() if int(event.get("question_number") or 0) == qnum]
        attempts = len(events)
        if attempts < 3:
            return {"score": 0.0, "attempts": attempts, "flips": 0, "label": "", "last_outcome": ""}
        outcomes = [bool(event.get("correct")) for event in events]
        flips = sum(1 for idx in range(1, len(outcomes)) if outcomes[idx] != outcomes[idx - 1])
        if not flips:
            return {
                "score": 0.0,
                "attempts": attempts,
                "flips": 0,
                "label": "",
                "last_outcome": "correct" if outcomes[-1] else "wrong",
            }
        flip_ratio = flips / max(1, attempts - 1)
        recency_bonus = 15.0 if attempts >= 2 and outcomes[-1] != outcomes[-2] else 0.0
        score = round(min(100.0, flip_ratio * 70.0 + min(20.0, (attempts - 2) * 4.0) + recency_bonus), 1)
        label = "High" if score >= 60 else ("Moderate" if score >= 35 else "")
        return {
            "score": score,
            "attempts": attempts,
            "flips": flips,
            "label": label,
            "last_outcome": "correct" if outcomes[-1] else "wrong",
        }

    def _apply_adaptive_answer_order(self, questions):
        reordered = []
        for q in questions:
            rec = self._progress_record(q, create=False) or {}
            attempts = int(rec.get("attempts", 0))
            if attempts > 0 and len(q.get("correct", [])) == 1:
                seed_src = f"{q.get('question_number')}|{self.answer_order_epoch}|{attempts}|{int(rec.get('wrong_count', 0))}|{int(rec.get('correct_count', 0))}"
                reordered.append(adaptive_shuffle_question(q, seed_src))
            else:
                reordered.append(q)
        return reordered

    def _clone_questions(self, source):
        questions = [stable_shuffle_question(q) for q in copy.deepcopy(source)]
        self.apply_progress_to_questions(questions)
        return questions

    def load_from_path(self, path: Path):
        try:
            self.data = load_bank(path)
        except Exception as e:
            logging.exception("Invalid question bank: %s", path)
            messagebox.showerror("Invalid question bank", str(e))
            return
        self.bank_path = path
        self.progress_path = self.progress_file_for_bank(path)
        self.load_progress_if_present()
        self.master_questions = self._clone_questions(self.data["questions"])
        self._reset_runtime_question_state(self.master_questions)
        self._rebuild_followup_candidate_index()
        domains = sorted({q.get("domain", "Unsorted") for q in self.master_questions})
        topics = sorted(
            {str(topic).strip() for q in self.master_questions for topic in q.get("topics", []) if str(topic).strip()}
        )
        self.domain_combo["values"] = ["All domains"] + domains
        self.topic_combo["values"] = ["All topics"] + topics
        domain_pref = str(self.config.get("last_domain") or "All domains")
        topic_pref = str(self.config.get("last_topic") or "All topics")
        status_pref = self.normalize_status_filter(self.config.get("last_status"))
        self.domain_filter_var.set(domain_pref if domain_pref in self.domain_combo["values"] else "All domains")
        self.topic_filter_var.set(topic_pref if topic_pref in self.topic_combo["values"] else "All topics")
        self.status_filter_var.set(status_pref if status_pref in self.status_combo["values"] else "All questions")
        source_pref = self.normalize_session_source(self.config.get("session_source"))
        self.session_source_var.set(source_pref)
        self.clear_active_session(reset_clock=True)
        self.invalidate_learning_state(prewarm=True, prewarm_delay_ms=0)
        self.root.title(f"{APP_NAME} {APP_VERSION} - {path.name}")

    def reset_session(self):
        if not self.questions:
            return
        if not messagebox.askyesno("Reset session", "Clear answers, flags, and restart this session?"):
            return
        for q in self.questions:
            clear_runtime_answer_state(q, clear_flagged=True)
            rec = self._progress_record(q, create=False)
            if rec:
                self._progress_questions()[self._question_key(q)] = set_progress_flag(rec, False)
            self.set_flag_by_question_number(q.get("question_number"), False)
        self.save_progress()
        self.elapsed_base = 0
        self.clock_started_at = time.time()
        self.index = 0
        self.checkpoints_saved = set()
        self.exam_reveal = self.active_session_mode != MODE_EXAM
        self.checkpoint_label.configure(text="")
        self.save_session(show_notice=False)
        self.refresh_question_list()
        self.render_question()

    def format_timer(self, seconds):
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h:02}:{m:02}:{s:02}"

    def _tick(self):
        self.timer_label.configure(text=f"Time {self.format_timer(self.current_elapsed_seconds())}")
        self.root.after(1000, self._tick)

    def _on_content_configure(self, event=None):
        self.content_canvas.configure(scrollregion=self.content_canvas.bbox("all"))

    def _apply_responsive_card_padding(self, width):
        width = int(width or 0)
        if width and width < 900:
            pad_x = 10
        elif width and width < 1100:
            pad_x = 12
        else:
            pad_x = 16
        self.card_header.configure(padx=pad_x)
        self.content_frame.configure(padx=pad_x)
        self.card_action_panel.configure(padx=max(8, pad_x - 2))
        return pad_x

    def _on_canvas_configure(self, event):
        self.content_canvas.itemconfig(self.canvas_window, width=event.width)
        pad_x = self._apply_responsive_card_padding(event.width)
        wrap = max(420, event.width - (pad_x * 2 + 38))
        self.question_label.configure(wraplength=wrap)
        self.issue_label.configure(wraplength=wrap)
        self.general_card.configure(wraplength=wrap)
        for row in self.choice_rows.values():
            row.set_wrap(wrap - 80)
        self._layout_action_buttons(event.width)

    def _bind_mousewheel(self, event=None):
        if not self.mousewheel_bound:
            self.root.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
            self.root.bind_all("<ButtonPress-2>", self._on_middle_drag_start, add="+")
            self.root.bind_all("<B2-Motion>", self._on_middle_drag, add="+")
            self.mousewheel_bound = True

    def _unbind_mousewheel(self, event=None):
        return

    def _pointer_in_content_area(self):
        widget = self.content_canvas.winfo_containing(self.root.winfo_pointerx(), self.root.winfo_pointery())
        while widget is not None:
            if widget == self.content_canvas:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _canvas_pointer_xy(self, event):
        return (
            event.x_root - self.content_canvas.winfo_rootx(),
            event.y_root - self.content_canvas.winfo_rooty(),
        )

    def _on_mousewheel(self, event):
        if self._pointer_in_content_area():
            units = int(-1 * (event.delta / 120))
            if units:
                self.content_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_middle_drag_start(self, event):
        if self._pointer_in_content_area():
            x, y = self._canvas_pointer_xy(event)
            self.content_canvas.scan_mark(x, y)

    def _on_middle_drag(self, event):
        if self._pointer_in_content_area():
            x, y = self._canvas_pointer_xy(event)
            self.content_canvas.scan_dragto(x, y, gain=1)

    def toggle_general_explanation(self):
        self.render_general_explanation()

    def render_general_explanation(self):
        if not hasattr(self, "general_card"):
            return
        q = self.current_question() if getattr(self, "questions", None) else None
        if (
            q
            and q.get("answered")
            and self.explanation_recall_var.get()
            and self._question_correct(q)
            and not q.get("recall_ready", False)
        ):
            self.general_card.pack_forget()
            return
        self.general_card.pack(fill="x", pady=(0, 10))

    def _rebuild_more_menu(self, include_maintenance=False):
        self.more_menu.delete(0, tk.END)
        self.more_menu.add_command(label="Save Session", command=lambda: self.save_session(show_notice=True))
        self.more_menu.add_command(label="Analytics Dashboard", command=self.open_analytics_window)
        self.more_menu.add_command(label="Reported Issues", command=self.open_issue_review_window)
        if include_maintenance:
            self.more_menu.add_separator()
            self.more_menu.add_command(
                label=self.flag_btn.cget("text").title(),
                command=self.toggle_flag,
                state=str(self.flag_btn.cget("state") or "normal"),
            )
            self.more_menu.add_command(
                label=self.suspend_btn.cget("text").title(),
                command=self.toggle_suspend,
                state=str(self.suspend_btn.cget("state") or "normal"),
            )
            self.more_menu.add_command(
                label=self.report_issue_btn.cget("text").title(),
                command=self.report_current_question_issue,
                state=str(self.report_issue_btn.cget("state") or "normal"),
            )
            self.more_menu.add_command(
                label="Redo Question", command=self.redo_question, state=str(self.redo_btn.cget("state") or "normal")
            )

    def _layout_action_buttons(self, width=None):
        if not hasattr(self, "card_action_panel"):
            return
        self._ensure_sticky_action_bar()
        width = width or self.card_action_panel.winfo_width() or self.card.winfo_width()
        narrow = bool(width) and width < 1120
        for button in (
            self.submit_btn,
            self.flag_btn,
            self.suspend_btn,
            self.report_issue_btn,
            self.redo_btn,
            self.next_unanswered_btn,
            self.super_confident_action_btn,
        ):
            button.pack_forget()
        if self.submit_btn_visible:
            self.submit_btn.pack(side="left")
        if not narrow:
            self.flag_btn.pack(side="left", padx=(8, 0))
            self.suspend_btn.pack(side="left", padx=(8, 0))
            self.report_issue_btn.pack(side="left", padx=(8, 0))
            self.redo_btn.pack(side="left", padx=(8, 0))
        self.next_unanswered_btn.pack(side="left", padx=(8, 0))
        self.super_confident_action_btn.pack(side="left", padx=(8, 0))
        self._rebuild_more_menu(include_maintenance=narrow)

    def _ensure_sticky_action_bar(self):
        if not hasattr(self, "card_action_outer"):
            return
        if not self.card_action_outer.winfo_manager():
            self.card_action_outer.pack(fill="x", side="bottom")
        self.card_action_outer.lift()

    def clear_study_hud_pulse(self):
        for after_id in list(getattr(self, "study_hud_pulse_after_ids", []) or []):
            try:
                self.root.after_cancel(after_id)
            except Exception:
                pass
        self.study_hud_pulse_after_ids = []
        try:
            self.gamef.configure(bg="#f7f9fc")
            self.study_hud_label.configure(bg="#f7f9fc")
        except Exception:
            pass

    def pulse_study_hud(self, kind="answer"):
        if not self.gamification_enabled() or not hasattr(self, "study_hud_label"):
            return
        self.clear_study_hud_pulse()
        if kind == "milestone":
            frames = [("#fff4cd", "#8a5d00"), ("#fff9e8", "#9f712f"), ("#f7f9fc", self.study_hud_label.cget("fg"))]
        elif kind == "wrong":
            frames = [("#fff1f1", RED), ("#fbfcfe", RED), ("#f7f9fc", self.study_hud_label.cget("fg"))]
        else:
            frames = [("#ecf7ef", GREEN), ("#f6fbf8", GREEN), ("#f7f9fc", self.study_hud_label.cget("fg"))]

        def apply_frame(index):
            bg, fg = frames[index]
            try:
                self.gamef.configure(bg=bg)
                self.study_hud_label.configure(bg=bg, fg=fg)
            except Exception:
                return
            if index < len(frames) - 1:
                after_id = self.root.after(150, lambda: apply_frame(index + 1))
                self.study_hud_pulse_after_ids.append(after_id)

        apply_frame(0)

    def clear_answer_toast(self):
        if getattr(self, "answer_toast_after_id", None):
            try:
                self.root.after_cancel(self.answer_toast_after_id)
            except Exception:
                pass
            self.answer_toast_after_id = None
        self.answer_toast_text = ""
        try:
            self.top_feedback_label.place_forget()
        except Exception:
            pass

    def show_answer_toast(self, text, kind="answer", duration_ms=None):
        if not self.gamification_enabled() or not str(text or "").strip():
            return
        if getattr(self, "answer_toast_after_id", None):
            try:
                self.root.after_cancel(self.answer_toast_after_id)
            except Exception:
                pass
        self.answer_toast_text = str(text).strip()
        self.answer_toast_kind = str(kind or "answer")
        palette = {
            "answer": ("#ecf7ef", "#17643a"),
            "streak": ("#fff4cd", "#8a5d00"),
            "recovery": ("#eaf3ff", BLUE),
            "wrong": ("#fff1f1", RED),
        }
        bg, fg = palette.get(self.answer_toast_kind, palette["answer"])
        self.top_feedback_label.configure(text=self.answer_toast_text, bg=bg, fg=fg)
        if not self.top_feedback_label.winfo_manager():
            self.top_feedback_label.place(relx=0.83, rely=0.74, anchor="center", relwidth=0.3)
        if duration_ms is None:
            duration_ms = {"Light": 1300, "Standard": 2100, "High": 2900}.get(self.reward_intensity(), 2100)
        self.answer_toast_after_id = self.root.after(duration_ms, self.clear_answer_toast)

    def _render_answer_toast(self):
        text = str(getattr(self, "answer_toast_text", "") or "").strip()
        if not text:
            self.top_feedback_label.place_forget()
            return
        self.top_feedback_label.configure(text=text)
        if not self.top_feedback_label.winfo_manager():
            self.top_feedback_label.place(relx=0.83, rely=0.74, anchor="center", relwidth=0.3)

    def _compact_quest_text(self):
        if not self.gamification_enabled():
            return "Quests off"
        if not self.current_quests:
            return ""
        active = [quest for quest in self.current_quests if not quest.get("completed")]
        quest = active[0] if active else self.current_quests[0]
        title = str(quest.get("title") or "Quest")
        progress = int(quest.get("progress") or 0)
        target = int(quest.get("target") or 0)
        suffix = " done" if quest.get("completed") else ""
        return f"Quest {title} {progress}/{target}{suffix}"

    def _reward_summary_text(self):
        if not self.gamification_enabled():
            return "Rewards off"
        if not self.session_rewards:
            return "No badges yet"
        if len(self.session_rewards) == 1:
            return f"Badge: {self.session_rewards[-1]}"
        return f"Badges: {len(self.session_rewards)} | Latest: {self.session_rewards[-1]}"

    def _update_study_hud(self, summary, combo, meta):
        if not hasattr(self, "study_hud_label"):
            return
        if not self.gamification_enabled():
            self.study_hud_label.configure(
                text=f"Study HUD | Level {meta.get('level', 1)} | {meta.get('xp', 0)} XP | Rewards off", fg=MUTED
            )
            return
        medal = str((summary or {}).get("medal") or "-")
        correct_combo = int((combo or {}).get("correct") or 0)
        parts = [
            f"Level {meta.get('level', 1)}",
            f"{meta.get('xp', 0)} XP",
            f"{medal} pace",
        ]
        if correct_combo:
            parts.append(f"Streak x{correct_combo}")
        quest_text = self._compact_quest_text()
        if quest_text:
            parts.append(quest_text)
        if self.session_rewards:
            parts.append(f"Latest badge: {self.session_rewards[-1]}")
        hud = " | ".join(parts)
        self.study_hud_label.configure(text=hud, fg=self._medal_color(medal))

    def _apply_compact_review_visibility(self, q=None):
        compact_answering = bool(self.compact_review_var.get()) and q is not None and not q.get("answered")
        has_reward_banner = bool(str(self.reward_banner_label.cget("text")).strip())
        has_answer_chip = bool(str(self.score_label.cget("text")).strip())
        has_reward_state = bool(self.session_rewards or self.session_answer_history)
        show_compact_rewards = bool(
            self.compact_review_var.get()
            and self.gamification_enabled()
            and (has_reward_banner or has_answer_chip or has_reward_state)
        )
        self.session_label.pack_forget()
        if compact_answering or not str(self.checkpoint_label.cget("text")).strip():
            self.checkpoint_label.pack_forget()
        else:
            self.checkpoint_label.pack(fill="x", pady=(2, 0), after=self.question_count)
        if not has_reward_banner:
            self.reward_banner_label.pack_forget()
        else:
            after = (
                self.score_label
                if self.score_label.winfo_manager()
                else (self.checkpoint_label if self.checkpoint_label.winfo_manager() else self.question_count)
            )
            self.reward_banner_label.pack(fill="x", pady=(2, 0), after=after)
        if self.compact_review_var.get() and not show_compact_rewards:
            self.gamef.pack_forget()
        else:
            after = (
                self.reward_banner_label
                if self.reward_banner_label.winfo_manager()
                else (self.checkpoint_label if self.checkpoint_label.winfo_manager() else self.question_count)
            )
            self.gamef.pack(fill="x", pady=(4, 0), after=after)

    def _update_progress(self):
        total = len(self.questions)
        answered = sum(1 for q in self.questions if q.get("answered"))
        correct = sum(1 for q in self.questions if q.get("answered") and self._question_correct(q))
        wrong = answered - correct
        flagged = sum(1 for q in self.questions if q.get("flagged"))
        self.refresh_session_quests()
        summary = self._build_session_summary() if self.questions else {"medal": "-", "accuracy": 0.0}
        combo = self._current_combo_stats()
        meta = self._progress_meta()
        pct = int(answered / total * 100) if total else 0
        self.progress_label.configure(text=f"Progress: {answered}/{total} ({pct}%)")
        self.progress_bar["value"] = pct
        if self.active_session_mode == MODE_EXAM and not self.exam_reveal:
            footer_text = f"QUESTION {self.index + 1} of {total}   |   Answered: {answered}/{total}   |   Flagged: {flagged}   |   Exam locked"
        else:
            footer_text = f"QUESTION {self.index + 1} of {total}   |   Answered: {answered}/{total}   |   Correct: {correct}   |   Wrong: {wrong}   |   Flagged: {flagged}"
        self.question_count.configure(text=footer_text)
        if self.gamification_enabled():
            self._maybe_show_combo_burst()
            self.maybe_trigger_pass_score_victory(summary)
        else:
            self.clear_answer_feedback_chip()
        self._update_study_hud(summary, combo, meta)
        if self.session_path:
            self.session_label.configure(text=f"Session file: {self.session_path.name}")


def main():
    root = tk.Tk()
    TestingEngineApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
