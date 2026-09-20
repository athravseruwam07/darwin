from datetime import timedelta

from darwin.io.oak import OakCamera


class TimestampedFrame:
    def getTimestamp(self):
        return timedelta(seconds=123.456)


def test_oak_uses_host_synchronized_capture_timestamp():
    assert OakCamera.capture_timestamp(TimestampedFrame()) == 123.456


class MissingTimestampFrame:
    def getTimestamp(self):
        raise RuntimeError("timestamp unavailable")


def test_oak_rejects_frames_without_capture_timestamp():
    assert OakCamera.capture_timestamp(MissingTimestampFrame()) is None
