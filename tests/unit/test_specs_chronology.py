from ludamus.specs.chronology import resolve_facilitator_session_edit


class TestResolveFacilitatorSessionEdit:
    def test_override_none_defers_to_sphere_default_true(self):
        result = resolve_facilitator_session_edit(
            event_override=None, sphere_default=True
        )
        assert result is True

    def test_override_none_defers_to_sphere_default_false(self):
        result = resolve_facilitator_session_edit(
            event_override=None, sphere_default=False
        )
        assert result is False

    def test_override_true_wins_over_sphere_false(self):
        result = resolve_facilitator_session_edit(
            event_override=True, sphere_default=False
        )
        assert result is True

    def test_override_false_wins_over_sphere_true(self):
        result = resolve_facilitator_session_edit(
            event_override=False, sphere_default=True
        )
        assert result is False
