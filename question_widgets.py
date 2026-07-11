import tkinter as tk

from ui_typography import (
    CHOICE_BADGE_FONT,
    CHOICE_DENSE_BADGE_FONT,
    CHOICE_DENSE_DETAIL_FONT,
    CHOICE_DENSE_MARK_FONT,
    CHOICE_DENSE_TEXT_FONT,
    CHOICE_DENSE_WRONG_DETAIL_FONT,
    CHOICE_DETAIL_FONT,
    CHOICE_MARK_FONT,
    CHOICE_TEXT_FONT,
    QUESTION_WRONG_EXPLANATION_FONT,
)
from ui_theme import (
    BLUE,
    BORDER,
    CARD,
    DARK,
    GREEN,
    HOVER_BADGE,
    HOVER_BG,
    HOVER_BORDER,
    LIGHT_BLUE,
    LIGHT_GREEN,
    LIGHT_RED,
    MUTED,
    RED,
    TEXT,
)


class ChoiceRow:
    def __init__(self, master, letter, on_toggle):
        self.letter = letter
        self.outer = tk.Frame(master, bg=BORDER)
        self.inner = tk.Frame(self.outer, bg=CARD, padx=10, pady=8)
        self.inner.pack(fill='both', expand=True, padx=1, pady=1)
        self.main_line = tk.Frame(self.inner, bg=CARD)
        self.main_line.pack(fill='x')
        self.badge = tk.Label(self.main_line, text=letter, width=3, bg='#f2f4f7', fg=DARK, font=CHOICE_BADGE_FONT, padx=6, pady=6)
        self.badge.pack(side='left', padx=(0, 8))
        self.text = tk.Label(self.main_line, text='', bg=CARD, fg=TEXT, justify='left', anchor='w', wraplength=850, font=CHOICE_TEXT_FONT)
        self.text.pack(side='left', fill='both', expand=True)
        self.mark = tk.Label(self.main_line, text='', bg=CARD, fg=MUTED, font=CHOICE_MARK_FONT, padx=8)
        self.mark.pack(side='right')
        self.detail_wrap = tk.Frame(self.inner, bg=CARD)
        self.detail_toggle = tk.Button(
            self.detail_wrap,
            text='Show why',
            font=('Segoe UI', 7, 'bold'),
            bd=1,
            relief='solid',
            bg='#f7f9fc',
            fg=BLUE,
            activebackground='#edf4fb',
            activeforeground=BLUE,
            padx=7,
            pady=1,
            command=self.toggle_detail,
        )
        self.detail = tk.Label(self.detail_wrap, text='', bg=CARD, fg=MUTED, justify='left', anchor='w', wraplength=800, font=CHOICE_DETAIL_FONT, padx=0, pady=0)
        self.detail_text = ''
        self.detail_visible = False
        self.is_dense = False
        self.interactive = True
        self.style_name = 'default'
        self.hovering = False
        self.default_detail_font = CHOICE_DETAIL_FONT
        self._text_value = None
        self._wrap_width = None
        self._density_value = None
        self._effective_style = None
        self._interactive_value = None
        self._detail_signature = None
        for w in (self.outer, self.inner, self.main_line, self.badge, self.text, self.mark, self.detail):
            w.bind('<Button-1>', lambda e, l=letter, anchor=self.outer: on_toggle(l, anchor))
            w.bind('<Enter>', lambda e: self._handle_hover(True))
            w.bind('<Leave>', lambda e: self._handle_hover(False))

    def pack(self, **kwargs):
        self.outer.pack(**kwargs)

    def pack_forget(self):
        self.outer.pack_forget()

    def set_text(self, value):
        if value == self._text_value:
            return
        self._text_value = value
        self.text.configure(text=value)

    def set_wrap(self, width):
        width = max(350, width)
        if width == self._wrap_width:
            return
        self._wrap_width = width
        self.text.configure(wraplength=width)
        self.detail.configure(wraplength=width)

    def set_density(self, dense=False):
        self.is_dense = bool(dense)
        if self.is_dense == self._density_value:
            return
        self._density_value = self.is_dense
        if self.is_dense:
            self.inner.configure(padx=8, pady=5)
            self.badge.configure(font=CHOICE_DENSE_BADGE_FONT, padx=4, pady=4)
            self.text.configure(font=CHOICE_DENSE_TEXT_FONT)
            self.mark.configure(font=CHOICE_DENSE_MARK_FONT)
            self.default_detail_font = CHOICE_DENSE_DETAIL_FONT
            self.detail.configure(font=self.default_detail_font)
        else:
            self.inner.configure(padx=10, pady=8)
            self.badge.configure(font=CHOICE_BADGE_FONT, padx=6, pady=6)
            self.text.configure(font=CHOICE_TEXT_FONT)
            self.mark.configure(font=CHOICE_MARK_FONT)
            self.default_detail_font = CHOICE_DETAIL_FONT
            self.detail.configure(font=self.default_detail_font)

    def _show_mark(self, text, bg, fg):
        self.mark.configure(text=text, bg=bg, fg=fg, padx=8)
        if not self.mark.winfo_manager():
            self.mark.pack(side='right')

    def _hide_mark(self, bg):
        self.mark.configure(text='', bg=bg, fg=MUTED, padx=0)
        self.mark.pack_forget()

    def _apply_style(self, style_name=None):
        if style_name is not None:
            self.style_name = style_name
        style = self.style_name
        if self.hovering and self.interactive and style == 'default':
            style = 'hover'
        if style == self._effective_style:
            return
        self._effective_style = style
        palette = {
            'default': {'outer': BORDER, 'inner': CARD, 'badge_bg': '#f2f4f7', 'badge_fg': DARK, 'text_fg': TEXT, 'mark_bg': CARD, 'mark_fg': MUTED},
            'hover': {'outer': HOVER_BORDER, 'inner': HOVER_BG, 'badge_bg': HOVER_BADGE, 'badge_fg': BLUE, 'text_fg': TEXT, 'mark_bg': HOVER_BG, 'mark_fg': BLUE},
            'pending': {'outer': BLUE, 'inner': LIGHT_BLUE, 'badge_bg': BLUE, 'badge_fg': 'white', 'text_fg': TEXT, 'mark_bg': LIGHT_BLUE, 'mark_fg': BLUE},
            'correct': {'outer': GREEN, 'inner': LIGHT_GREEN, 'badge_bg': GREEN, 'badge_fg': 'white', 'text_fg': TEXT, 'mark_bg': LIGHT_GREEN, 'mark_fg': GREEN},
            'wrong': {'outer': RED, 'inner': LIGHT_RED, 'badge_bg': RED, 'badge_fg': 'white', 'text_fg': TEXT, 'mark_bg': LIGHT_RED, 'mark_fg': RED},
        }[style]
        self.outer.configure(bg=palette['outer'])
        self.inner.configure(bg=palette['inner'])
        self.main_line.configure(bg=palette['inner'])
        self.badge.configure(bg=palette['badge_bg'], fg=palette['badge_fg'])
        self.text.configure(bg=palette['inner'], fg=palette['text_fg'])
        self.mark.configure(bg=palette['mark_bg'], fg=palette['mark_fg'])
        self.detail_wrap.configure(bg=palette['inner'])
        self.detail.configure(bg=palette['inner'])

    def _handle_hover(self, is_hovering):
        self.hovering = bool(is_hovering)
        self._apply_style()

    def reset(self):
        self.detail_text = ''
        self.detail_visible = False
        self.interactive = True
        self._interactive_value = True
        self._detail_signature = None
        self._apply_style('default')
        self._hide_mark(CARD)
        self.detail_wrap.pack_forget()
        self.detail_toggle.pack_forget()
        self.detail.pack_forget()
        self.detail.configure(font=self.default_detail_font)

    def set_interactive(self, enabled):
        enabled = bool(enabled)
        if enabled == self._interactive_value:
            return
        self._interactive_value = enabled
        self.interactive = enabled
        if not self.interactive:
            self.hovering = False
        self._apply_style()

    def mark_pending(self, multi=False):
        self._apply_style('pending')
        self._show_mark('PICKED' if multi else '', LIGHT_BLUE, BLUE)

    def mark_selected_correct(self):
        self._apply_style('correct')
        self._show_mark('OK', LIGHT_GREEN, GREEN)

    def mark_selected_wrong(self):
        self._apply_style('wrong')
        self._hide_mark(LIGHT_RED)

    def mark_correct_unselected(self):
        self._apply_style('correct')
        self._show_mark('OK', LIGHT_GREEN, GREEN)

    def set_detail(self, text, bg=None, fg=None, expanded=False, show_toggle=True, emphasis=False):
        detail_text = str(text or '').strip()
        signature = (detail_text, bg, fg, bool(expanded), bool(show_toggle), bool(emphasis), self.is_dense)
        if signature == self._detail_signature:
            return
        self._detail_signature = signature
        self.detail_text = detail_text
        self.detail.configure(text=self.detail_text)
        if bg is not None:
            self.detail.configure(bg=bg)
            self.detail_wrap.configure(bg=bg)
        if fg is not None:
            self.detail.configure(fg=fg)
        if emphasis:
            wrong_font = CHOICE_DENSE_WRONG_DETAIL_FONT if self.is_dense else QUESTION_WRONG_EXPLANATION_FONT
            self.detail.configure(font=wrong_font)
        else:
            self.detail.configure(font=self.default_detail_font)
        self.detail_visible = bool(expanded)
        if self.detail_text:
            self.detail_wrap.pack(fill='x', pady=(6, 0))
            if show_toggle:
                self.detail_toggle.configure(text=('Hide why' if self.detail_visible else 'Show why'))
                self.detail_toggle.pack(anchor='w', pady=(0, 4))
            else:
                self.detail_toggle.pack_forget()
            if self.detail_visible or not show_toggle:
                self.detail.pack(fill='x')
            else:
                self.detail.pack_forget()
        else:
            self.detail_wrap.pack_forget()
            self.detail_toggle.pack_forget()
            self.detail.pack_forget()

    def toggle_detail(self):
        if not self.detail_text:
            return
        self.detail_visible = not self.detail_visible
        self.detail_toggle.configure(text=('Hide why' if self.detail_visible else 'Show why'))
        if self.detail_visible:
            self.detail.pack(fill='x')
        else:
            self.detail.pack_forget()
