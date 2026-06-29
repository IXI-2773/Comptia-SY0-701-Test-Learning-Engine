from collections import Counter

import random
import time
import tkinter as tk
from tkinter import ttk
from typing import cast

from app_constants import (
    MILESTONE_SPECS,
    MODE_EXAM,
    QUEST_COUNT_OPTIONS,
    QUEST_VARIANTS,
    QUESTION_TAG_BOSS_ROUND,
    QUESTION_TAG_STEALTH_CHECKPOINT,
    REWARD_INTENSITY_OPTIONS,
)
from progress_models import ProgressMeta, QuestStat, SessionHistoryEntry, session_history_entry_from_summary
from progress_store import is_active_weak, is_review_due, is_suspended, now_iso
from session_models import QuestProgressState
from ui_theme import AMBER, BG, BLUE, CARD, GREEN, MUTED, RED, TEXT
from widget_models import RewardHistoryWidgetRegistry

try:
    import winsound
except Exception:
    winsound = None


class GameRewardsMixin:
    PASS_SCORE_THRESHOLD = 70.0
    MEDAL_COLORS = {
        "Platinum": "#697f91",
        "Gold": "#b8860b",
        "Silver": "#7b8794",
        "Bronze": "#9a6336",
        "-": MUTED,
    }
    COMBO_COLORS = {
        "cold": MUTED,
        "warm": BLUE,
        "hot": AMBER,
        "fire": "#b8860b",
    }

    def _medal_color(self, medal: str) -> str:
        return self.MEDAL_COLORS.get(str(medal or "-"), MUTED)

    def _combo_heat_color(self, correct_streak: int) -> str:
        if correct_streak >= 10:
            return self.COMBO_COLORS["fire"]
        if correct_streak >= 5:
            return self.COMBO_COLORS["hot"]
        if correct_streak >= 3:
            return self.COMBO_COLORS["warm"]
        return self.COMBO_COLORS["cold"]

    def clear_victory_animation(self):
        for after_id in list(getattr(self, "victory_after_ids", []) or []):
            try:
                self.root.after_cancel(after_id)
            except Exception:
                pass
        self.victory_after_ids = []

    def clear_answer_feedback_chip(self):
        for after_id in list(getattr(self, "answer_feedback_after_ids", []) or []):
            try:
                self.root.after_cancel(after_id)
            except Exception:
                pass
        self.answer_feedback_after_ids = []
        try:
            self.score_label.configure(text="", bg=BG, fg=MUTED)
            self.score_label.pack_forget()
        except Exception:
            pass

    def clear_answer_result_overlay(self):
        for after_id in list(getattr(self, "answer_result_after_ids", []) or []):
            try:
                self.root.after_cancel(after_id)
            except Exception:
                pass
        self.answer_result_after_ids = []
        try:
            self.answer_result_overlay.place_forget()
        except Exception:
            pass

    def show_answer_result_overlay(self, is_correct):
        if not self.gamification_enabled() or not hasattr(self, "answer_result_overlay"):
            return
        self.clear_answer_result_overlay()
        text = "Correct" if is_correct else "Review this one"
        bg = "#e7f6ec" if is_correct else "#fff0f0"
        fg = GREEN if is_correct else RED
        try:
            self.answer_result_overlay.configure(text=text, bg=bg, fg=fg)
            self.answer_result_overlay.place(relx=0.5, rely=0.42, anchor="center", relwidth=0.3)
            self.answer_result_overlay.lift()
        except Exception:
            return
        duration = {"Light": 550, "Standard": 850, "High": 1050}.get(self.reward_intensity(), 850)
        after_id = self.root.after(duration, self.clear_answer_result_overlay)
        self.answer_result_after_ids.append(after_id)

    def clear_reward_banner(self):
        if self.reward_banner_after_id:
            self.root.after_cancel(self.reward_banner_after_id)
            self.reward_banner_after_id = None
        self.reward_banner_label.configure(text="")

    def gamification_enabled(self):
        return bool(self.gamification_enabled_var.get())

    def reward_intensity(self):
        value = str(self.reward_intensity_var.get() or "Standard").strip().title()
        return value if value in tuple(REWARD_INTENSITY_OPTIONS) else "Standard"

    def _feedback_cooldown_seconds(self):
        return {"Light": 2.8, "Standard": 1.7, "High": 0.9}.get(self.reward_intensity(), 1.7)

    def emit_micro_feedback(self, kind="reward"):
        if (
            not self.gamification_enabled()
            or not self.micro_feedback_var.get()
            or not self.reward_sounds_var.get()
            or kind not in ("level", "milestone")
            or winsound is None
        ):
            return
        try:
            tone = winsound.MB_OK if kind == "milestone" else winsound.MB_ICONASTERISK
            winsound.MessageBeep(tone)
        except Exception:
            pass

    def show_reward_banner(self, message, kind="reward", duration_ms=None, bypass_cooldown=False):
        if not self.gamification_enabled():
            return
        now = time.time()
        if not bypass_cooldown and now - self.last_reward_feedback_at < self._feedback_cooldown_seconds():
            return
        self.last_reward_feedback_at = now
        self.clear_reward_banner()
        palette = {
            "reward": GREEN,
            "quest": BLUE,
            "level": BLUE,
            "milestone": AMBER,
        }
        self.reward_banner_label.configure(text=message, fg=palette.get(kind, GREEN))
        self.show_reward_moment(message, kind=kind, duration_ms=duration_ms)
        try:
            self._apply_compact_review_visibility(self.current_question() if self.questions else None)
            self.pulse_study_hud("milestone" if kind in ("milestone", "level", "quest") else "answer")
        except Exception:
            pass
        self.emit_micro_feedback(kind=kind)
        if duration_ms is None:
            duration_ms = {"Light": 1800, "Standard": 2500, "High": 3200}.get(self.reward_intensity(), 2500)
        self.reward_banner_after_id = self.root.after(duration_ms, self.clear_reward_banner)

    def show_reward_moment(self, message, kind="reward", duration_ms=None):
        if not self.gamification_enabled() or not str(message or "").strip():
            return
        text = str(message).strip()
        replacements = {
            "Level up! You reached ": "Level ",
            "Quest complete: ": "Quest ",
            "Milestone unlocked: ": "Badge ",
            "Pass line crossed: ": "Pass line ",
        }
        for old, new in replacements.items():
            text = text.replace(old, new, 1)
        if len(text) > 46:
            text = text[:43].rstrip() + "..."
        self.show_answer_toast(
            text,
            kind=("streak" if kind in ("milestone", "quest", "level") else "answer"),
            duration_ms=duration_ms or 1800,
        )

    def refresh_reward_badges(self):
        if not self.gamification_enabled():
            self.reward_badges_text = "Rewards: disabled"
            self.reward_badges_fg = MUTED
            return
        if self.session_rewards:
            self.reward_badges_text = "Rewards: " + " | ".join(self.session_rewards)
            self.reward_badges_fg = GREEN
        else:
            self.reward_badges_text = "Rewards: none yet"
            self.reward_badges_fg = MUTED

    def maybe_trigger_pass_score_victory(self, summary):
        if (
            not self.gamification_enabled()
            or getattr(self, "pass_score_victory_unlocked", False)
            or self.active_session_mode == MODE_EXAM
            and not getattr(self, "exam_reveal", False)
        ):
            return
        answered = int((summary or {}).get("answered", 0))
        accuracy = float((summary or {}).get("accuracy", 0.0))
        if answered < 5 or accuracy < self.PASS_SCORE_THRESHOLD:
            return
        self.pass_score_victory_unlocked = True
        self.show_reward_banner(
            f"Pass line crossed: {accuracy:.1f}% accuracy. Keep it above {int(self.PASS_SCORE_THRESHOLD)}.",
            kind="milestone",
            duration_ms=3800,
            bypass_cooldown=True,
        )
        self.animate_pass_score_victory(summary)

    def animate_pass_score_victory(self, summary):
        if not self.gamification_enabled():
            return
        self.clear_victory_animation()
        medal = str((summary or {}).get("medal") or "-")
        medal_color = self._medal_color(medal)
        frames = [
            ("Pass score reached", "#fff8df", medal_color),
            ("Pass score reached *", "#fff2bd", "#9f712f"),
            ("Pass score reached **", "#fff8df", medal_color),
            (f"Medal pace: {medal}", BG, medal_color),
        ]

        def apply_frame(index):
            text, bg, fg = frames[index]
            try:
                self.reward_banner_label.configure(text=text, bg=bg, fg=fg)
                self._apply_compact_review_visibility(self.current_question() if self.questions else None)
            except Exception:
                return
            if index < len(frames) - 1:
                after_id = self.root.after(220, lambda: apply_frame(index + 1))
                self.victory_after_ids.append(after_id)
            else:
                after_id = self.root.after(1800, lambda: self.reward_banner_label.configure(bg=BG, fg=GREEN))
                self.victory_after_ids.append(after_id)

        apply_frame(0)

    def _session_reward_specs(self):
        history = list(self.session_answer_history)
        if not history:
            return []
        correct = [entry for entry in history if entry.get("correct")]
        current_streak = 0
        for entry in reversed(history):
            if not entry.get("correct"):
                break
            current_streak += 1
        sure_correct = sum(1 for entry in history if entry.get("correct") and entry.get("confidence") == "Sure")
        recovered_hits = sum(1 for entry in history if entry.get("correct") and entry.get("was_active_weak"))
        total_answered = len(history)
        wrong = total_answered - len(correct)
        misread_misses = sum(1 for entry in history if str(entry.get("miss_reason") or "") == "Misread")
        boss_clears = sum(
            1
            for entry in history
            if str(entry.get("session_tag") or "").startswith(QUESTION_TAG_BOSS_ROUND) and entry.get("correct")
        )
        specs = []
        if correct:
            specs.append(("first_win", "First Win", "Unlocked First Win: you got the set moving."))
        if current_streak >= 3:
            specs.append(("streak_3", "3-Streak", "Unlocked 3-Streak: you are building momentum."))
        if current_streak >= 5:
            specs.append(("streak_5", "5-Streak", "Unlocked 5-Streak: that is a strong run."))
        if current_streak >= 10:
            specs.append(("streak_10", "10-Streak", "Unlocked 10-Streak: you are in a serious groove."))
        if sure_correct >= 5:
            specs.append(("sure_hand", "Sure Hand", "Unlocked Sure Hand: five confident hits locked in."))
        if recovered_hits >= 1:
            specs.append(
                ("recovery_hit", "Recovery Hit", "Unlocked Recovery Hit: you cleaned up an active weak question.")
            )
        if recovered_hits >= 3:
            specs.append(
                ("comeback_3", "Comeback x3", "Unlocked Comeback x3: three weak questions recovered in this set.")
            )
        if total_answered >= 10:
            specs.append(("focus_10", "Focus 10", "Unlocked Focus 10: ten questions completed this round."))
        if wrong == 0 and total_answered >= 5:
            specs.append(("perfect_focus", "Perfect Focus", "Unlocked Perfect Focus: a clean run with no misses."))
        if misread_misses == 0 and total_answered >= 6:
            specs.append(("clean_read", "Clean Read", "Unlocked Clean Read: no misread misses this session."))
        if boss_clears >= 1:
            specs.append(("boss_clear", "Boss Clear", "Unlocked Boss Clear: you beat a boss-round question."))
        return specs

    def unlock_session_rewards(self):
        if not self.gamification_enabled():
            self.refresh_reward_badges()
            return
        unlocked_messages = []
        for key, badge, message in self._session_reward_specs():
            if key in self.unlocked_rewards:
                continue
            self.unlocked_rewards.add(key)
            self.session_rewards.append(badge)
            unlocked_messages.append(message)
        self.refresh_reward_badges()
        if unlocked_messages:
            self.show_reward_banner(unlocked_messages[-1], kind="reward")

    def _level_for_xp(self, xp):
        xp = max(0, int(xp))
        return 1 + (xp // 120)

    def _current_combo_stats(self):
        correct_streak = 0
        recovery_streak = 0
        sure_streak = 0
        for entry in reversed(self.session_answer_history):
            if entry.get("correct"):
                correct_streak += 1
            else:
                break
        for entry in reversed(self.session_answer_history):
            if entry.get("correct") and entry.get("was_active_weak"):
                recovery_streak += 1
            else:
                break
        for entry in reversed(self.session_answer_history):
            if entry.get("correct") and entry.get("confidence") == "Sure":
                sure_streak += 1
            else:
                break
        return {"correct": correct_streak, "recovery": recovery_streak, "sure": sure_streak}

    def _next_reward_hint(self):
        if not self.gamification_enabled():
            return ""
        history = list(self.session_answer_history)
        if not history:
            return "First Win ready"
        combo = self._current_combo_stats()
        correct_streak = int(combo.get("correct", 0))
        if correct_streak < 3 and "streak_3" not in self.unlocked_rewards:
            return f"{3 - correct_streak} to 3-Streak"
        if correct_streak < 5 and "streak_5" not in self.unlocked_rewards:
            return f"{5 - correct_streak} to 5-Streak"
        if correct_streak < 10 and "streak_10" not in self.unlocked_rewards:
            return f"{10 - correct_streak} to 10-Streak"
        sure_hits = sum(1 for entry in history if entry.get("correct") and entry.get("confidence") == "Sure")
        if sure_hits < 5 and "sure_hand" not in self.unlocked_rewards:
            return f"{5 - sure_hits} sure hits to Sure Hand"
        if "clean_read" not in self.unlocked_rewards:
            return "Clean Read in reach"
        return "Keep the medal pace"

    def _maybe_show_combo_burst(self):
        if not self.gamification_enabled():
            return
        streak = int(self._current_combo_stats().get("correct", 0))
        if streak < 5 or streak % 5 != 0:
            return
        if streak in self.session_combo_burst_markers:
            return
        self.session_combo_burst_markers.add(streak)
        self.show_reward_banner(
            f"Hot streak x{streak}: lock in the next one.",
            kind="milestone",
            duration_ms=2200,
            bypass_cooldown=True,
        )

    def show_answer_feedback_chip(self, q, is_correct, xp_gained, was_active_weak=False, was_due=False):
        if not self.gamification_enabled():
            return
        self.clear_answer_feedback_chip()
        try:
            self.pulse_study_hud("answer" if is_correct else "wrong")
        except Exception:
            pass
        try:
            self.show_answer_result_overlay(is_correct)
        except Exception:
            pass
        combo = self._current_combo_stats()
        parts = []
        toast_kind = "answer"
        if is_correct:
            streak = int(combo.get("correct", 0))
            if was_active_weak:
                toast_kind = "recovery"
                parts.append(f"Recovered weak question +{int(xp_gained)} XP")
            elif streak >= 3:
                toast_kind = "streak"
                parts.append(f"Momentum x{streak} +{int(xp_gained)} XP")
            else:
                parts.append(f"Nice hit +{int(xp_gained)} XP")
            if streak >= 2:
                parts.append(f"streak x{streak}")
            if was_active_weak:
                parts.append("weak item cleaned up")
            if was_due:
                parts.append("Due review cleared")
            hint = self._next_reward_hint()
            if hint:
                parts.append(f"next: {hint}")
        else:
            toast_kind = "wrong"
            parts.append(f"Try again +{int(xp_gained)} XP")
            miss_reason = str(q.get("last_miss_reason") or "").strip()
            if miss_reason:
                parts.append(miss_reason)
            else:
                parts.append("Follow-up queued")
        text = " | ".join(parts)
        try:
            self.show_answer_toast(text, kind=toast_kind)
        except Exception:
            pass
        self.score_label.configure(text="", bg=BG, fg=MUTED)
        self.score_label.pack_forget()

    def _session_max_correct_streak(self):
        best = 0
        current = 0
        for entry in self.session_answer_history:
            if entry.get("correct"):
                current += 1
                best = max(best, current)
            else:
                current = 0
        return best

    def _session_medal_name(self):
        return self._build_session_summary()["medal"]

    def _quest_feasible(self, spec):
        if not self.questions:
            return False
        records = self._progress_questions()
        kind = spec["kind"]
        target = int(spec["target"])
        if kind in ("answered_total", "correct_total", "sure_correct", "perfect_focus", "correct_streak"):
            return target <= len(self.questions)
        if kind == "domain_spread":
            domains = {q.get("domain") or "Unsorted" for q in self.questions}
            return len(domains) >= target
        if kind in ("recovery_hits", "weak_attempts"):
            weak_count = sum(1 for q in self.questions if is_active_weak(records.get(self._question_key(q), {})))
            return weak_count >= 1 and target <= max(1, weak_count)
        if kind == "due_correct":
            due_count = sum(1 for q in self.questions if is_review_due(records.get(self._question_key(q), {})))
            return due_count >= target
        return True

    def choose_session_quests(self):
        if not self.gamification_enabled():
            self.current_quests = []
            self.quest_completion_keys = set()
            return
        available = [dict(spec) for spec in QUEST_VARIANTS if self._quest_feasible(spec)]
        if not available:
            self.current_quests = []
            self.quest_completion_keys = set()
            return
        meta: ProgressMeta = self._progress_meta()
        quest_stats = meta.setdefault("quest_stats", {})
        recent_session_history = meta.get("session_history", [])[-4:]
        recent_keys = {item.get("quest_key") for item in recent_session_history if item.get("quest_key")}
        count = max(1, min(5, int(str(self.quest_count_var.get() or "3"))))
        rng = random.Random(self.current_session_signature() + str(len(self.questions)))
        weighted = []
        for spec in available:
            stat = cast(QuestStat, quest_stats.get(spec["key"], {"offered": 0, "completed": 0}))
            used = int(stat.get("offered", 0))
            completed = int(stat.get("completed", 0))
            completion_rate = completed / used if used else 0.0
            variety_bonus = 0.0 if spec["key"] in recent_keys else 2.5
            usage_bonus = max(0.0, 4.0 - min(4.0, used * 0.4))
            difficulty_pull = abs(0.55 - completion_rate)
            balance_score = variety_bonus + usage_bonus + (1.5 - difficulty_pull * 2.0)
            weighted.append((balance_score + rng.random(), spec))
        weighted.sort(key=lambda item: item[0], reverse=True)
        chosen = []
        used_kinds = set()
        for _score, spec in weighted:
            if spec["kind"] in used_kinds and len(chosen) < min(2, count):
                continue
            used_kinds.add(spec["kind"])
            spec["progress"] = 0
            spec["completed"] = False
            chosen.append(spec)
            existing = quest_stats.get(spec["key"], {"offered": 0, "completed": 0})
            quest_stats[spec["key"]] = {
                "offered": int(existing.get("offered", 0)) + 1,
                "completed": int(existing.get("completed", 0)),
            }
            if len(chosen) >= count:
                break
        self.current_quests = [cast(QuestProgressState, spec) for spec in chosen]
        self.quest_completion_keys = set()
        self.refresh_session_quests()

    def _quest_progress_value(self, quest):
        kind = quest.get("kind")
        history = self.session_answer_history
        if kind == "answered_total":
            return len(history)
        if kind == "correct_total":
            return sum(1 for entry in history if entry.get("correct"))
        if kind == "correct_streak":
            return self._session_max_correct_streak()
        if kind == "sure_correct":
            return sum(1 for entry in history if entry.get("correct") and entry.get("confidence") == "Sure")
        if kind == "recovery_hits":
            return sum(1 for entry in history if entry.get("correct") and entry.get("was_active_weak"))
        if kind == "domain_spread":
            return len({entry.get("domain") or "Unsorted" for entry in history})
        if kind == "weak_attempts":
            return sum(1 for entry in history if entry.get("was_active_weak"))
        if kind == "due_correct":
            return sum(1 for entry in history if entry.get("correct") and entry.get("was_due"))
        if kind == "perfect_focus":
            return sum(1 for entry in history if entry.get("correct") and entry.get("confidence") != "Guessed")
        return 0

    def refresh_session_quests(self):
        for quest in self.current_quests:
            progress = self._quest_progress_value(quest)
            quest["progress"] = min(progress, int(quest.get("target", 0)))
            quest["completed"] = progress >= int(quest.get("target", 0))

    def _quest_text(self):
        if not self.gamification_enabled():
            return "Quests: disabled"
        if not self.current_quests:
            return "Quests: not started"
        parts = []
        for quest in self.current_quests:
            marker = "OK" if quest.get("completed") else ""
            parts.append(
                f"{quest['title']} {quest.get('progress', 0)}/{quest['target']}{(' ' + marker) if marker else ''}"
            )
        return "Quests: " + " | ".join(parts)

    def _apply_xp_for_answer(self, q, is_correct, feedback, was_active_weak=False, was_due=False):
        if not self.gamification_enabled():
            return 0
        meta: ProgressMeta = self._progress_meta()
        stats = meta["stats"]
        gained = 3
        confidence = str((feedback or {}).get("confidence") or "Sure")
        stats["total_answered"] += 1
        stats["domains_seen"] = sorted(set(stats.get("domains_seen", [])) | {str(q.get("domain") or "Unsorted")})
        if is_correct:
            gained = 12
            stats["total_correct"] += 1
            if confidence == "Sure":
                gained += 5
            elif confidence == "Unsure":
                gained += 3
            else:
                gained += 1
            if was_due:
                gained += 4
            if was_active_weak:
                gained += 6
                stats["total_recovered"] += 1
            if str(q.get("session_tag") or "").startswith(QUESTION_TAG_BOSS_ROUND):
                gained += 8
        level_before = int(meta.get("level", 1))
        meta["xp"] = int(meta.get("xp", 0)) + gained
        meta["level"] = self._level_for_xp(meta["xp"])
        self.session_xp_gained += gained
        if meta["level"] > level_before:
            self.show_reward_banner(f"Level up! You reached Level {meta['level']}.", kind="level", bypass_cooldown=True)
        self.schedule_progress_save()
        return gained

    def _unlock_quest_rewards(self):
        if not self.gamification_enabled():
            return
        meta: ProgressMeta = self._progress_meta()
        unlocked = []
        for quest in self.current_quests:
            if not quest.get("completed") or quest.get("key") in self.quest_completion_keys:
                continue
            self.quest_completion_keys.add(quest["key"])
            unlocked.append(quest["title"])
            meta["xp"] = int(meta.get("xp", 0)) + 18
            self.session_xp_gained += 18
            quest_stats = meta.setdefault("quest_stats", {})
            stat = quest_stats.get(quest["key"], {"offered": 0, "completed": 0})
            quest_stats[quest["key"]] = {
                "offered": int(stat.get("offered", 0)),
                "completed": int(stat.get("completed", 0)) + 1,
            }
            if quest["title"] not in meta["badges"]:
                meta["badges"].append(quest["title"])
        if unlocked:
            meta["level"] = self._level_for_xp(meta["xp"])
            self.show_reward_banner(f"Quest complete: {unlocked[-1]} (+18 XP)", kind="quest")
            self.schedule_progress_save()

    def _check_global_milestones(self):
        if not self.gamification_enabled():
            return
        meta: ProgressMeta = self._progress_meta()
        stats = meta["stats"]
        unlocked = []
        milestones = set(meta.get("milestones", []))
        derived = {"domain_count": len(stats.get("domains_seen", []))}
        for key, title, stat_name, target in MILESTONE_SPECS:
            value = derived.get(stat_name, stats.get(stat_name, 0))
            if value < target or key in milestones:
                continue
            milestones.add(key)
            unlocked.append(title)
            meta["xp"] = int(meta.get("xp", 0)) + 35
            self.session_xp_gained += 35
        if unlocked:
            meta["milestones"] = sorted(milestones)
            meta["level"] = self._level_for_xp(meta["xp"])
            self.show_reward_banner(
                f"Milestone unlocked: {unlocked[-1]} (+35 XP)", kind="milestone", bypass_cooldown=True
            )
            self.schedule_progress_save()

    def maybe_trigger_boss_round(self, current_q):
        if self.active_session_mode == MODE_EXAM or not self.boss_rounds_enabled_var.get():
            return []
        answered_count = len(self.session_answer_history)
        if not answered_count or answered_count % 10 != 0 or answered_count in self.session_boss_markers:
            return []
        records = self._progress_questions()
        current_qnums = {item.get("question_number") for item in self.questions}
        ranked = []
        for candidate in self.master_questions:
            qnum = candidate.get("question_number")
            if qnum in current_qnums:
                continue
            rec = records.get(self._question_key(candidate), {})
            if is_suspended(rec):
                continue
            volatility = self.question_volatility(candidate)
            score = (
                (6 if is_active_weak(rec) else 0)
                + (4 if is_review_due(rec) else 0)
                + int(rec.get("wrong_count", 0))
                + (3 if candidate.get("domain") == current_q.get("domain") else 0)
                + int(volatility.get("score", 0) / 15)
            )
            ranked.append((score, qnum, candidate))
        ranked.sort(key=lambda row: (row[0], -row[1]), reverse=True)
        inserted = self._insert_followup_questions(
            current_q, [candidate for _score, _qnum, candidate in ranked[:1]], QUESTION_TAG_BOSS_ROUND
        )
        if inserted:
            self.session_boss_markers.add(answered_count)
        return inserted

    def maybe_trigger_stealth_checkpoint(self, current_q):
        if self.active_session_mode == MODE_EXAM:
            return []
        if not current_q.get("answered") or not self._question_correct(current_q):
            return []
        answered_count = len(self.session_answer_history)
        if answered_count < 4 or answered_count in self.session_stealth_markers:
            return []
        rec = self._progress_record(current_q, create=False) or {}
        qnum = int(current_q.get("question_number") or 0)
        question_history_map = {
            qnum: [event for event in self._recent_history(28) if int(event.get("question_number") or 0) == qnum]
        }
        question_stability = {qnum: self._question_stability_score(current_q, rec, question_history_map.get(qnum, []))}
        source_rows, source_map = self._build_source_agreement_rows(self.master_questions)
        _source_trust_rows, source_trust_map = self._build_source_trust_rows(self.master_questions, source_rows)
        latent_rows = self._build_latent_weakness_rows(
            self._progress_questions(),
            question_stability,
            question_history_map,
            source_map,
            source_trust_map,
            [current_q],
        )
        latent_score = float(latent_rows[0]["score"]) if latent_rows else 0.0
        kind, unit = self._coverage_unit_for_question(current_q)
        transfer_rows, transfer_map = self._build_transfer_strength_rows(
            self._progress_questions(), question_stability, self.master_questions
        )
        del transfer_rows
        transfer_score = float((transfer_map.get(f"{kind}::{unit}") or {}).get("score", 72.0))
        source_label = str((source_map.get(qnum) or {}).get("label", "Single-source only"))
        trigger = 0.0
        confidence = str(current_q.get("last_confidence") or rec.get("last_confidence") or "")
        if confidence == "Guessed":
            trigger += 6.0
        elif confidence == "Unsure":
            trigger += 4.0
        if latent_score:
            trigger += min(8.0, latent_score / 4.0)
        if transfer_score < 68.0:
            trigger += (68.0 - transfer_score) * 0.18
        if source_label in ("Single-source only", "Source conflict"):
            trigger += 2.5
        volatility = self.question_volatility(current_q)
        if float(volatility.get("score", 0.0)) >= 35.0:
            trigger += 2.0
        if trigger < 6.0:
            return []
        records = self._progress_questions()
        current_qnums = {item.get("question_number") for item in self.questions}
        current_topic = self._primary_topic_label(current_q)
        current_source = str(current_q.get("source_name") or "")
        current_stem = self._stem_style_for_question(current_q)
        ranked = []
        for candidate in self.master_questions:
            candidate_qnum = candidate.get("question_number")
            if candidate_qnum == current_q.get("question_number") or candidate_qnum in current_qnums:
                continue
            candidate_rec = records.get(self._question_key(candidate), {})
            if is_suspended(candidate_rec):
                continue
            candidate_kind, candidate_unit = self._coverage_unit_for_question(candidate)
            same_unit = candidate_kind == kind and candidate_unit == unit
            same_topic = self._primary_topic_label(candidate) == current_topic
            if not same_unit and not same_topic:
                continue
            same_source = str(candidate.get("source_name") or "") == current_source
            candidate_stem = self._stem_style_for_question(candidate)
            candidate_source_row = source_map.get(int(candidate_qnum or 0), {"score": 0.8})
            score = (
                (9 if same_unit else 5)
                + (3 if same_topic else 0)
                + (3 if not same_source else 0)
                + (4 if candidate_stem != current_stem else 0)
                + float(candidate_source_row.get("score", 0.8)) * 3.0
                - int(candidate_rec.get("attempts", 0)) * 0.12
            )
            ranked.append((score, int(candidate_qnum or 0), candidate))
        ranked.sort(key=lambda row: (row[0], -row[1]), reverse=True)
        inserted = self._insert_followup_questions(
            current_q, [candidate for _score, _qnum, candidate in ranked[:1]], QUESTION_TAG_STEALTH_CHECKPOINT
        )
        if inserted:
            self.session_stealth_markers.add(answered_count)
        return inserted

    def _build_session_summary(self):
        history = list(self.session_answer_history)
        answered = len(history)
        correct = sum(1 for entry in history if entry.get("correct"))
        wrong = answered - correct
        accuracy = round((correct / answered) * 100, 1) if answered else 0.0
        recoveries = sum(1 for entry in history if entry.get("correct") and entry.get("was_active_weak"))
        sure_correct = sum(1 for entry in history if entry.get("correct") and entry.get("confidence") == "Sure")
        fast_wrongs = [
            entry
            for entry in history
            if not entry.get("correct")
            and float(entry.get("response_seconds") or 0.0) > 0
            and float(entry.get("response_seconds") or 0.0) <= 7.0
        ]
        boss_hits = sum(
            1
            for entry in history
            if str(entry.get("session_tag") or "").startswith(QUESTION_TAG_BOSS_ROUND) and entry.get("correct")
        )
        misread_misses = sum(1 for entry in history if str(entry.get("miss_reason") or "") == "Misread")
        perfect_focus = answered >= 5 and wrong == 0 and misread_misses == 0
        decision_quality = (
            self._decision_quality_score(self._recent_history(28), self.progress_summary()) if history else 0.0
        )
        if accuracy >= 92 and recoveries >= 1 and decision_quality >= 80:
            medal = "Platinum"
        elif accuracy >= 84 and decision_quality >= 70:
            medal = "Gold"
        elif accuracy >= 72:
            medal = "Silver"
        elif answered:
            medal = "Bronze"
        else:
            medal = "-"
        replay = [
            f"Q{entry.get('question_number')} ({entry.get('domain') or 'Unsorted'})"
            for entry in history
            if not entry.get("correct")
        ][:8]
        topics = {
            str(topic).strip()
            for entry in history
            for topic in list(entry.get("topics") or [])
            if str(topic).strip()
        }
        domains = {str(entry.get("domain") or "").strip() for entry in history if entry.get("domain")}
        source_labels = {str(entry.get("source_label") or "").strip() for entry in history if entry.get("source_label")}
        weak_attempts = sum(1 for entry in history if entry.get("was_active_weak"))
        due_reviews = sum(1 for entry in history if entry.get("was_due"))
        new_learning = max(0, answered - weak_attempts - due_reviews)
        missed_domains = Counter(str(entry.get("domain") or "Unsorted") for entry in history if not entry.get("correct"))
        if wrong and missed_domains:
            focus = missed_domains.most_common(1)[0][0]
            diagnosis = f"Focus next: replay misses in {focus}."
        elif recoveries:
            diagnosis = f"Strong recovery: {recoveries} weak item{'s' if recoveries != 1 else ''} moved forward."
        else:
            diagnosis = "Clean learning pass: keep widening coverage next set."
        variety = f"Variety {len(topics)} topics / {len(domains)} domains / {len(source_labels)} sources"
        return {
            "answered": answered,
            "correct": correct,
            "wrong": wrong,
            "accuracy": accuracy,
            "recoveries": recoveries,
            "sure_correct": sure_correct,
            "medal": medal,
            "fast_wrong_count": len(fast_wrongs),
            "boss_hits": boss_hits,
            "perfect_focus": perfect_focus,
            "replay_strip": replay,
            "quests_completed": sum(1 for quest in self.current_quests if quest.get("completed")),
            "new_learning": new_learning,
            "weak_attempts": weak_attempts,
            "due_reviews": due_reviews,
            "variety": variety,
            "diagnosis": diagnosis,
        }

    def maybe_finish_session(self, force=False):
        if not self.questions or any(not q.get("answered") for q in self.questions):
            return
        signature = f"{self.current_session_signature()}:{len(self.session_answer_history)}"
        if signature == self.session_completion_signature:
            return
        self.session_completion_signature = signature
        summary = self._build_session_summary()
        self.last_session_summary = summary
        meta: ProgressMeta = self._progress_meta()
        meta["stats"]["sessions_completed"] += 1
        if summary["perfect_focus"]:
            meta["stats"]["perfect_sessions"] += 1
        session_history = list(meta.get("session_history", []))
        quest_key = self.current_quests[0]["key"] if self.current_quests else ""
        session_history.append(
            session_history_entry_from_summary(
                at=now_iso(),
                mode=self.active_session_mode,
                source=self.active_source_label,
                answered=summary["answered"],
                correct=summary["correct"],
                accuracy=summary["accuracy"],
                recoveries=summary["recoveries"],
                medal=summary["medal"],
                xp_gained=self.session_xp_gained,
                quest_key=quest_key,
                quests_completed=summary["quests_completed"],
                boss_hits=summary["boss_hits"],
                speed_risk=summary["fast_wrong_count"],
            )
        )
        meta["session_history"] = session_history[-120:]
        medal_bonus = {"Bronze": 15, "Silver": 25, "Gold": 40, "Platinum": 60}.get(summary["medal"], 0)
        if medal_bonus:
            meta["xp"] = int(meta.get("xp", 0)) + medal_bonus
            self.session_xp_gained += medal_bonus
            meta["level"] = self._level_for_xp(meta["xp"])
        self._check_global_milestones()
        self.schedule_progress_save()
        self.save_session(show_notice=False)
        self.show_session_celebration(summary)

    def show_session_celebration(self, summary=None):
        if not self.gamification_enabled() or not self.celebration_popups_var.get():
            return
        summary = summary or self.last_session_summary or self._build_session_summary()
        self.last_session_summary = summary
        self.show_session_loot_card(summary)
        self.show_reward_moment(
            f"Loot card ready: {summary['medal']} medal, +{self.session_xp_gained} XP",
            kind="milestone",
            duration_ms=2600,
        )

    def clear_session_loot_card(self):
        try:
            self.loot_card.pack_forget()
            self.loot_title_label.configure(text="")
            self.loot_stats_label.configure(text="")
            self.loot_detail_label.configure(text="")
        except Exception:
            pass

    def show_session_loot_card(self, summary):
        if not hasattr(self, "loot_card"):
            return
        medal_color = self._medal_color(summary["medal"])
        replay_text = (
            " | ".join(summary["replay_strip"]) if summary["replay_strip"] else "Clean finish. No misses to replay."
        )
        rewards = ", ".join(self.session_rewards[-6:]) if self.session_rewards else "No new session badges yet."
        bg = "#fff8df" if summary["medal"] in {"Gold", "Platinum"} else "#f7f9fc"
        for widget in (self.loot_card, self.loot_title_label, self.loot_stats_label, self.loot_detail_label):
            widget.configure(bg=bg)
        self.loot_title_label.configure(text=f"Loot card: {summary['medal']} medal session", fg=medal_color)
        self.loot_stats_label.configure(
            text=(
                f"+{self.session_xp_gained} XP  |  Accuracy {summary['accuracy']}%  |  "
                f"Correct {summary['correct']}  |  Recovered {summary['recoveries']}  |  Quests {summary['quests_completed']}"
            )
        )
        self.loot_detail_label.configure(
            text=(
                f"{summary.get('variety', 'Variety -')}  |  New {summary.get('new_learning', 0)}  |  "
                f"Weak {summary.get('weak_attempts', 0)}  |  Due {summary.get('due_reviews', 0)}\n"
                f"{summary.get('diagnosis', '')}  |  Replay: {replay_text}  |  Rewards: {rewards}"
            )
        )
        if not self.loot_card.winfo_manager():
            pack_options = {"fill": "x", "pady": (4, 0)}
            if getattr(self, "reward_banner_label", None) is not None and self.reward_banner_label.winfo_manager():
                pack_options["after"] = self.reward_banner_label
            self.loot_card.pack(**pack_options)
        try:
            self._apply_compact_review_visibility(self.current_question() if self.questions else None)
        except Exception:
            pass

    def open_reward_history_window(self):
        if self.reward_history_window and self.reward_history_window.winfo_exists():
            self.reward_history_window.deiconify()
            self.reward_history_window.lift()
            self.refresh_reward_history_window()
            return
        win = tk.Toplevel(self.root)
        self.reward_history_window = win
        win.title("Rewards and History")
        win.geometry("980x700")
        win.configure(bg=BG)
        win.protocol("WM_DELETE_WINDOW", self.close_reward_history_window)
        top = tk.Frame(win, bg=BLUE, height=42)
        top.pack(fill="x")
        top.pack_propagate(False)
        tk.Label(top, text="Rewards and History", bg=BLUE, fg="white", font=("Segoe UI", 11, "bold"), padx=14).pack(
            side="left"
        )
        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=12)
        summary = tk.Label(
            body,
            text="",
            bg=CARD,
            fg=TEXT,
            justify="left",
            anchor="nw",
            padx=12,
            pady=10,
            relief="solid",
            bd=1,
            font=("Segoe UI", 10),
        )
        summary.pack(fill="x")
        notebook = ttk.Notebook(body)
        notebook.pack(fill="both", expand=True, pady=(12, 0))
        rewards_text = tk.Text(
            notebook, wrap="word", font=("Segoe UI", 10), bg=CARD, fg=TEXT, relief="flat", padx=10, pady=10
        )
        notebook.add(rewards_text, text="Rewards")
        history_tree_frame = tk.Frame(notebook, bg=CARD)
        notebook.add(history_tree_frame, text="Session History")
        history_tree = ttk.Treeview(
            history_tree_frame,
            columns=("at", "mode", "accuracy", "medal", "xp", "recoveries", "boss", "speed"),
            show="headings",
        )
        for key, label, width in (
            ("at", "When", 150),
            ("mode", "Mode", 110),
            ("accuracy", "Accuracy", 80),
            ("medal", "Medal", 90),
            ("xp", "XP", 70),
            ("recoveries", "Recoveries", 90),
            ("boss", "Boss", 60),
            ("speed", "Speed Risk", 90),
        ):
            history_tree.heading(key, text=label)
            history_tree.column(key, width=width, anchor="w")
        history_tree.pack(side="left", fill="both", expand=True)
        history_sb = tk.Scrollbar(history_tree_frame, command=history_tree.yview)
        history_sb.pack(side="right", fill="y")
        history_tree.configure(yscrollcommand=history_sb.set)
        trend_text = tk.Text(
            notebook, wrap="word", font=("Segoe UI", 10), bg=CARD, fg=TEXT, relief="flat", padx=10, pady=10
        )
        notebook.add(trend_text, text="Long Range")
        self.reward_history_widgets = cast(
            RewardHistoryWidgetRegistry,
            {"summary": summary, "rewards_text": rewards_text, "history_tree": history_tree, "trend_text": trend_text},
        )
        self.refresh_reward_history_window()

    def close_reward_history_window(self):
        if self.reward_history_window and self.reward_history_window.winfo_exists():
            self.reward_history_window.destroy()
        self.reward_history_window = None
        self.reward_history_widgets = cast(RewardHistoryWidgetRegistry, {})

    def refresh_reward_history_window(self):
        if not getattr(self, "reward_history_window", None) or not self.reward_history_window.winfo_exists():
            return
        meta: ProgressMeta = self._progress_meta()
        stats = meta.get("stats", {})
        badges = list(meta.get("badges", []))
        milestones = list(meta.get("milestones", []))
        sessions: list[SessionHistoryEntry] = list(meta.get("session_history", []))
        summary = (
            f"Level {meta.get('level', 1)}    XP {meta.get('xp', 0)}\n"
            f"Answered: {stats.get('total_answered', 0)}    Correct: {stats.get('total_correct', 0)}    Recovered: {stats.get('total_recovered', 0)}\n"
            f"Sessions: {stats.get('sessions_completed', 0)}    Perfect focus sessions: {stats.get('perfect_sessions', 0)}    Domains touched: {len(stats.get('domains_seen', []))}"
        )
        self.reward_history_widgets["summary"].configure(text=summary)
        rewards_text = self.reward_history_widgets["rewards_text"]
        rewards_text.configure(state="normal")
        rewards_text.delete("1.0", tk.END)
        rewards_text.insert(tk.END, "Badges\n\n")
        rewards_text.insert(tk.END, (", ".join(badges) if badges else "No badges unlocked yet.") + "\n\n")
        rewards_text.insert(tk.END, "Milestones\n\n")
        rewards_text.insert(tk.END, (", ".join(milestones) if milestones else "No milestones unlocked yet.") + "\n\n")
        rewards_text.insert(tk.END, "Quest Balancing Snapshot\n\n")
        quest_stats = meta.get("quest_stats", {})
        if quest_stats:
            for key, stat in sorted(quest_stats.items()):
                offered = int(stat.get("offered", 0))
                completed = int(stat.get("completed", 0))
                rate = round((completed / offered) * 100, 1) if offered else 0.0
                rewards_text.insert(tk.END, f"{key}: offered {offered}, completed {completed}, completion {rate}%\n")
        else:
            rewards_text.insert(tk.END, "Quest stats will appear after a few sessions.\n")
        rewards_text.configure(state="disabled")
        tree = self.reward_history_widgets["history_tree"]
        for item in tree.get_children():
            tree.delete(item)
        for row in reversed(sessions[-40:]):
            tree.insert(
                "",
                "end",
                values=(
                    str(row.get("at", ""))[:16].replace("T", " "),
                    row.get("mode", ""),
                    f"{row.get('accuracy', 0)}%",
                    row.get("medal", ""),
                    row.get("xp_gained", 0),
                    row.get("recoveries", 0),
                    row.get("boss_hits", 0),
                    row.get("speed_risk", 0),
                ),
            )
        trend_text = self.reward_history_widgets["trend_text"]
        trend_text.configure(state="normal")
        trend_text.delete("1.0", tk.END)
        if sessions:
            recent = sessions[-10:]
            avg_accuracy = round(sum(float(item.get("accuracy", 0.0)) for item in recent) / len(recent), 1)
            avg_xp = round(sum(int(item.get("xp_gained", 0)) for item in recent) / len(recent), 1)
            total_boss = sum(int(item.get("boss_hits", 0)) for item in recent)
            total_speed = sum(int(item.get("speed_risk", 0)) for item in recent)
            trend_text.insert(tk.END, f"Last {len(recent)} sessions average accuracy: {avg_accuracy}%\n")
            trend_text.insert(tk.END, f"Last {len(recent)} sessions average XP: {avg_xp}\n")
            trend_text.insert(tk.END, f"Boss clears in last {len(recent)} sessions: {total_boss}\n")
            trend_text.insert(tk.END, f"Speed-risk misses in last {len(recent)} sessions: {total_speed}\n\n")
            trend_text.insert(tk.END, "Recent session medals\n\n")
            for row in recent:
                trend_text.insert(
                    tk.END,
                    f"{str(row.get('at', ''))[:10]}  {row.get('medal', '')}  {row.get('accuracy', 0)}%  {row.get('mode', '')}\n",
                )
        else:
            trend_text.insert(tk.END, "Persistent performance history will appear after your first completed set.\n")
        trend_text.configure(state="disabled")

    def open_game_settings_window(self):
        if self.game_settings_window and self.game_settings_window.winfo_exists():
            self.game_settings_window.deiconify()
            self.game_settings_window.lift()
            return
        win = tk.Toplevel(self.root)
        self.game_settings_window = win
        win.title("Game Layer Settings")
        win.geometry("430x420")
        win.configure(bg=BG)
        win.protocol("WM_DELETE_WINDOW", self.close_game_settings_window)
        frame = tk.Frame(win, bg=CARD, bd=1, relief="solid", padx=14, pady=14)
        frame.pack(fill="both", expand=True, padx=14, pady=14)
        tk.Label(frame, text="Game Layer Settings", bg=CARD, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(anchor="w")
        tk.Checkbutton(
            frame,
            text="Enable rewards and gamification",
            variable=self.gamification_enabled_var,
            bg=CARD,
            fg=TEXT,
            anchor="w",
            command=self.on_game_setting_changed,
        ).pack(fill="x", pady=(12, 8))
        tk.Checkbutton(
            frame,
            text="Show end-of-set loot card",
            variable=self.celebration_popups_var,
            bg=CARD,
            fg=TEXT,
            anchor="w",
            command=self.on_game_setting_changed,
        ).pack(fill="x", pady=4)
        tk.Checkbutton(
            frame,
            text="Play celebration sounds (milestones only)",
            variable=self.reward_sounds_var,
            bg=CARD,
            fg=TEXT,
            anchor="w",
            command=self.on_game_setting_changed,
        ).pack(fill="x", pady=4)
        tk.Checkbutton(
            frame,
            text="Use extra celebration cues",
            variable=self.micro_feedback_var,
            bg=CARD,
            fg=TEXT,
            anchor="w",
            command=self.on_game_setting_changed,
        ).pack(fill="x", pady=4)
        tk.Checkbutton(
            frame,
            text="Enable boss rounds",
            variable=self.boss_rounds_enabled_var,
            bg=CARD,
            fg=TEXT,
            anchor="w",
            command=self.on_game_setting_changed,
        ).pack(fill="x", pady=4)
        tk.Label(frame, text="Reward intensity", bg=CARD, fg=TEXT, font=("Segoe UI", 9, "bold")).pack(
            anchor="w", pady=(14, 0)
        )
        ttk.Combobox(
            frame, textvariable=self.reward_intensity_var, state="readonly", values=REWARD_INTENSITY_OPTIONS
        ).pack(fill="x", pady=(4, 8))
        tk.Label(frame, text="Quest count per set", bg=CARD, fg=TEXT, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        ttk.Combobox(frame, textvariable=self.quest_count_var, state="readonly", values=QUEST_COUNT_OPTIONS).pack(
            fill="x", pady=(4, 8)
        )
        help_text = "Light keeps feedback quiet and short.\nStandard is balanced.\nHigh is more celebratory.\nChanges apply to new sets right away."
        tk.Label(frame, text=help_text, bg=CARD, fg=MUTED, justify="left", anchor="w").pack(fill="x", pady=(10, 0))
        tk.Button(
            frame,
            text="Close",
            font=("Segoe UI", 9, "bold"),
            bg=BLUE,
            fg="white",
            bd=0,
            padx=12,
            pady=8,
            command=self.close_game_settings_window,
        ).pack(anchor="e", pady=(16, 0))
        for var_name in ("reward_intensity_var", "quest_count_var"):
            getattr(self, var_name).trace_add("write", lambda *_args: self.on_game_setting_changed())

    def on_game_setting_changed(self):
        self.save_app_config()
        self.refresh_reward_badges()
        self._update_progress()
        self.refresh_reward_history_window()

    def close_game_settings_window(self):
        if self.game_settings_window and self.game_settings_window.winfo_exists():
            self.game_settings_window.destroy()
        self.game_settings_window = None
