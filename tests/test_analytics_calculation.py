import unittest

from analytics_recommendations import AnalyticsRecommendationInputs, build_analytics_recommendations


def _empty_inputs() -> AnalyticsRecommendationInputs:
    return AnalyticsRecommendationInputs(
        progress={"due": 0, "wrong": 0, "recovered": 0},
        decision_quality=0.0,
        volatile_rows=[],
        concept_clusters=[],
        confusion_pairs=[],
        interference_map_rows=[],
        coverage_gaps=[],
        objective_mastery_rows=[],
        prerequisite_debt_rows=[],
        knowledge_trace_rows=[],
        concept_memory_state_rows=[],
        wrong_answer_memory_rows=[],
        concept_half_life_rows=[],
        blind_spot_rows=[],
        expected_learning_gain_rows=[],
        confidence_compression_rows=[],
        compression_point_rows=[],
        abstraction_ladder_rows=[],
        recognition_retrieval_rows=[],
        robustness_rows=[],
        leverage_ranking_rows=[],
        generalization_rows=[],
        error_boundary_rows=[],
        counterfactual_distractor_rows=[],
        counterexample_training_rows=[],
        difficulty_rows=[],
        phrasing_rows=[],
        misconception_fingerprints=[],
        effort_efficiency_rows=[],
        decision_latency_rows=[],
        answer_latency_rows=[],
        confidence_mismatch_rows=[],
        cue_dependence_rows=[],
        latent_weakness_rows=[],
        transfer_strength_rows=[],
        reinforcement_distance_rows=[],
        delayed_probe_rows=[],
        synthesis_check_rows=[],
        contrast_rule_rows=[],
        retention_stress_rows=[],
        failure_mode_rows=[],
        concept_state_rows=[],
        source_trust_rows=[],
        burnout_risk={"label": "Low", "score": 0.0},
        source_agreement_rows=[],
        weak_domains=[],
        weak_topics=[],
    )


class AnalyticsCalculationTests(unittest.TestCase):
    def test_recommendations_fall_back_when_no_signals_exist(self):
        self.assertEqual(
            ["Answer more questions to unlock stronger recommendations."],
            build_analytics_recommendations(_empty_inputs()),
        )

    def test_recommendations_preserve_priority_text_for_core_signals(self):
        inputs = _empty_inputs()
        inputs.progress["due"] = 7
        inputs.objective_mastery_rows.append({"objective_code": "5.2", "mastery_score": 61, "stem_style_count": 2})
        inputs.weak_domains.append(
            {
                "domain": "Cloud Security",
                "readiness": 62.5,
                "stability": 51.0,
                "heat": 72.0,
                "trend": -4.2,
                "progress_active_weak": 3,
                "progress_due": 2,
            }
        )

        result = build_analytics_recommendations(inputs)

        self.assertIn("Start Due review with 7 questions due today.", result)
        self.assertTrue(any("Objective autopilot: 5.2 is only 61% mastered" in row for row in result))
        self.assertTrue(any("Cloud Security: readiness 62.5%" in row for row in result))


if __name__ == "__main__":
    unittest.main()
