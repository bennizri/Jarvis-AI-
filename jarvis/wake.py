import numpy as np

from .config import CONFIG


class WakeDetector:
    def __init__(self):
        import openwakeword
        from openwakeword.model import Model
        openwakeword.utils.download_models([CONFIG.wake_model])
        self.model = Model(wakeword_models=[CONFIG.wake_model],
                           inference_framework="onnx")

    def detect(self, frame: np.ndarray) -> bool:
        """frame: int16 mono, CONFIG.wake_frame_samples long."""
        score = self.model.predict(frame)[CONFIG.wake_model]
        if score >= CONFIG.wake_threshold:
            self.model.reset()
            return True
        return False

    def reset(self) -> None:
        """Clear internal audio buffer (call after the mic was used elsewhere)."""
        self.model.reset()


def _main():
    """Calibration: prints the score whenever the model reacts at all.

    Say 'Hey Jarvis' a few times; set CONFIG.wake_threshold just below
    the scores YOUR voice produces.
    """
    import sounddevice as sd
    det = WakeDetector()
    print(f"Say 'Hey Jarvis'... threshold={CONFIG.wake_threshold} (ctrl-c to stop)")
    n = CONFIG.wake_frame_samples
    with sd.InputStream(samplerate=CONFIG.sample_rate, channels=1,
                        dtype="int16", blocksize=n) as stream:
        while True:
            data, _ = stream.read(n)
            scores: dict = det.model.predict(data[:, 0])  # type: ignore[assignment]
            score = float(scores[CONFIG.wake_model])
            if score >= CONFIG.wake_threshold:
                det.model.reset()
                print(f"WAKE DETECTED  score={score:.2f}")
            elif score >= 0.1:
                print(f"  near miss     score={score:.2f}  (threshold {CONFIG.wake_threshold})")


if __name__ == "__main__":
    _main()
