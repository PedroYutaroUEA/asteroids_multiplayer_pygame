"""Tests for the FrameProfiler used by --profile-frames."""

from core.frame_stats import FrameProfiler, percentile


def test_percentile_endpoints_and_median():
    data = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile(data, 0) == 10.0
    assert percentile(data, 50) == 30.0
    assert percentile(data, 100) == 50.0


def test_percentile_empty_is_zero():
    assert percentile([], 95) == 0.0


def test_percentile_sorts_input():
    assert percentile([50.0, 10.0, 30.0, 20.0, 40.0], 50) == 30.0


def test_flush_emits_summary_and_resets(capsys):
    p = FrameProfiler(label="[t]", every_s=1.0)
    p.add("frame", 16.0)
    p.frame_done(0.0)  # opens the window at t=0
    p.add("frame", 18.0)
    p.frame_done(0.5)  # still inside the window -> silent
    assert capsys.readouterr().err == ""

    p.add("frame", 20.0)
    p.frame_done(1.2)  # crosses every_s -> flush
    err = capsys.readouterr().err
    assert "[t]" in err
    assert "fps=" in err
    assert "frame=" in err
    # window reset
    assert p._samples == {}
    assert p._frames == 0


def test_flush_without_frames_is_noop(capsys):
    p = FrameProfiler(every_s=1.0)
    p.flush(5.0)
    assert capsys.readouterr().err == ""
    assert p._window_start is None
