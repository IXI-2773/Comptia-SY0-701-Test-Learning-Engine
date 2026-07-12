import unittest

from smart_practice_worker import SmartPracticeWorkerSnapshot, build_detached_pool, build_detached_signal_payload


class _FakeSmartPracticeOwner:
    def __init__(self):
        raise AssertionError("Detached worker should not initialize the owner app.")

    def _build_smart_practice_signal_payload(self):
        return {
            "question_count": len(self.master_questions),
            "has_root": self.root is not None,
        }

    def _build_smart_practice_pool_compat(self, count, randomize=True, base_pool=None):
        return list(base_pool or self.master_questions)[: int(count)]


class SmartPracticeWorkerTests(unittest.TestCase):
    def test_detached_signal_payload_uses_snapshot_without_initializing_owner(self):
        snapshot = SmartPracticeWorkerSnapshot(
            master_questions=[{"question_number": 1}, {"question_number": 2}],
            questions=[],
            progress_data={"meta": {}},
            session_answer_history=[],
            active_session_mode="smart",
            smart_practice_signal_cache_key=None,
            smart_practice_signal_cache_payload=None,
            smart_practice_pool_cache={},
            progress_meta_cache_raw={},
            progress_meta_cache_value=None,
            base_pool=None,
        )

        payload = build_detached_signal_payload(_FakeSmartPracticeOwner, snapshot)

        self.assertEqual({"question_count": 2, "has_root": False}, payload)

    def test_detached_pool_builder_uses_snapshot_base_pool(self):
        snapshot = SmartPracticeWorkerSnapshot(
            master_questions=[{"question_number": 1}, {"question_number": 2}, {"question_number": 3}],
            questions=[],
            progress_data={"meta": {}},
            session_answer_history=[],
            active_session_mode="smart",
            smart_practice_signal_cache_key=None,
            smart_practice_signal_cache_payload=None,
            smart_practice_pool_cache={},
            progress_meta_cache_raw={},
            progress_meta_cache_value=None,
            base_pool=[{"question_number": 7}, {"question_number": 8}],
        )

        pool = build_detached_pool(
            _FakeSmartPracticeOwner, snapshot, count="1", randomize=False, base_pool=snapshot.base_pool
        )

        self.assertEqual([{"question_number": 7}], pool)


if __name__ == "__main__":
    unittest.main()
