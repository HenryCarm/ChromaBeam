"""
ChromaBeam Optical Color Classifier & Dynamic Calibrator
Extracts 3-bit binary states from RGB pixels with dynamic calibration against ambient lighting and monitor temperature.
"""

import numpy as np
from typing import Tuple, List, Optional


class AdaptiveColorClassifier:
    """
    Dynamically adjusts RGB decision boundaries using reference calibration swatches
    sampled from the optical frame border.
    """
    def __init__(self):
        # Default midpoint thresholds
        self.r_threshold = 128.0
        self.g_threshold = 128.0
        self.b_threshold = 128.0

    def calibrate(self, cal_samples: List[np.ndarray]):
        """
        Calibrates thresholds using the 5 reference colors:
        cal_samples: [Black, Red, Green, Blue, White] RGB vectors.
        """
        if len(cal_samples) < 5:
            return

        black = np.mean(cal_samples[0], axis=0) if cal_samples[0].ndim > 1 else cal_samples[0]
        red = np.mean(cal_samples[1], axis=0) if cal_samples[1].ndim > 1 else cal_samples[1]
        green = np.mean(cal_samples[2], axis=0) if cal_samples[2].ndim > 1 else cal_samples[2]
        blue = np.mean(cal_samples[3], axis=0) if cal_samples[3].ndim > 1 else cal_samples[3]
        white = np.mean(cal_samples[4], axis=0) if cal_samples[4].ndim > 1 else cal_samples[4]

        # Adaptive midpoint for each channel
        self.r_threshold = float((red[0] + green[0] + black[0]) / 3.0 + red[0]) / 2.0
        self.g_threshold = float((green[1] + red[1] + black[1]) / 3.0 + green[1]) / 2.0
        self.b_threshold = float((blue[2] + red[2] + black[2]) / 3.0 + blue[2]) / 2.0

        # Safety clamps
        self.r_threshold = np.clip(self.r_threshold, 40.0, 215.0)
        self.g_threshold = np.clip(self.g_threshold, 40.0, 215.0)
        self.b_threshold = np.clip(self.b_threshold, 40.0, 215.0)

    def classify_pixels(self, rgb_array: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Classifies an (N, 3) RGB array into 3 binary bit arrays (r_bit, g_bit, b_bit).
        """
        r_bit = (rgb_array[:, 0] > self.r_threshold).astype(np.uint8)
        g_bit = (rgb_array[:, 1] > self.g_threshold).astype(np.uint8)
        b_bit = (rgb_array[:, 2] > self.b_threshold).astype(np.uint8)
        return r_bit, g_bit, b_bit
