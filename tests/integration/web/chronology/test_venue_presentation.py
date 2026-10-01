from ludamus.gates.web.django.chronology.panel.views.venues import build_track_tone_map


def test_track_badge_colors_are_distinct_and_stable_for_thirteen_tracks():
    names = [f"Track {index:02}" for index in range(13)]

    forward = build_track_tone_map(names)
    reversed_input = build_track_tone_map(reversed(names))

    assert forward == reversed_input
    assert len(set(forward.values())) == len(names)
