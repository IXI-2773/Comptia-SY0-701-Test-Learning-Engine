from pathlib import Path

from storage_utils import load_json_or_backup, safe_write_json


DEFAULT_CONFIG = {
    'window_geometry': '1500x940',
    'analytics_geometry': '1220x780',
    'analytics_domain_widths': {},
    'analytics_topic_widths': {},
    'session_count': '25',
    'session_source': 'All',
    'random_order': True,
    'auto_next_correct': False,
    'explanation_recall_mode': True,
    'compact_review_mode': True,
    'dense_answers_mode': False,
    'gamification_enabled': True,
    'reward_intensity': 'Standard',
    'celebration_popups': True,
    'reward_sounds': False,
    'micro_feedback': False,
    'boss_rounds_enabled': True,
    'quest_count': '3',
    'sidebar_width_mode': 'Full',
    'last_domain': 'All domains',
    'last_topic': 'All topics',
    'last_status': 'All questions',
    'general_explanation_expanded': True,
}


def load_config(path: Path):
    if not path.exists():
        return DEFAULT_CONFIG.copy()
    data, _backup, _err = load_json_or_backup(path)
    if not isinstance(data, dict):
        return DEFAULT_CONFIG.copy()
    config = DEFAULT_CONFIG.copy()
    config.update({k: v for k, v in data.items() if k in config})
    return config


def save_config(path: Path, config):
    payload = DEFAULT_CONFIG.copy()
    payload.update({k: v for k, v in dict(config).items() if k in payload})
    safe_write_json(path, payload)
