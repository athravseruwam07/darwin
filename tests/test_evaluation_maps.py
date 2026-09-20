from darwin.evaluation import MAPS


def test_benchmark_covers_each_wheel_direction_reversal():
    assert "reverse_left" in MAPS
    assert "reverse_right" in MAPS
    assert "reverse_one" not in MAPS
