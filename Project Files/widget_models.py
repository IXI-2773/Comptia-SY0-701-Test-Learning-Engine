import tkinter as tk
from tkinter import ttk
from typing import TypedDict


class AnalyticsWidgetRegistry(TypedDict, total=False):
    summary_readiness: tk.Label
    summary_next_move: tk.Label
    summary_retention: tk.Label
    summary_momentum: tk.Label
    summary_source_health: tk.Label
    domain_tree: ttk.Treeview
    topic_tree: ttk.Treeview
    mastery_tree: ttk.Treeview
    hot_text: tk.Text
    patterns_text: tk.Text


class RewardHistoryWidgetRegistry(TypedDict, total=False):
    summary: tk.Label
    rewards_text: tk.Text
    history_tree: ttk.Treeview
    trend_text: tk.Text


class IssueReviewWidgetRegistry(TypedDict, total=False):
    summary: tk.Label
    tree: ttk.Treeview
    detail: tk.Label


class ScreenshotReviewWidgetRegistry(TypedDict, total=False):
    summary: tk.Label
    tree: ttk.Treeview
    detail: tk.Label
    prompt: tk.Text
    choices: dict[str, tk.StringVar]
    correct: tk.StringVar
    explanation: tk.Text
