import unittest

from study_question_utils import (
    coverage_unit_for_question,
    normalized_study_label,
    primary_topic_label,
    question_mentions_label,
    stem_style_for_question,
)


class StudyQuestionUtilsTests(unittest.TestCase):
    def test_primary_topic_and_coverage_unit_follow_existing_rules(self):
        question = {
            "question_number": 1,
            "domain": "Threats, Vulnerabilities, and Mitigations",
            "topics": ["Cloud Security"],
            "objective_code": "",
        }
        self.assertEqual("cloud security", primary_topic_label(question))
        self.assertEqual(("Topic", "cloud security"), coverage_unit_for_question(question))

    def test_stem_style_and_label_matching_remain_pure(self):
        question = {
            "prompt": "Which control best mitigates the issue?",
            "choices": {"A": "MTTR", "B": "RTO"},
        }
        self.assertEqual("Best fit", stem_style_for_question(question))
        self.assertTrue(question_mentions_label(question, "MTTR"))
        self.assertEqual(
            "threats vulnerabilities and mitigations",
            normalized_study_label("Threats, Vulnerabilities, and Mitigations"),
        )


if __name__ == "__main__":
    unittest.main()
