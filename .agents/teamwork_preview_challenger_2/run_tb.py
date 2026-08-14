import unittest
import test_offline_bundle_adversarial
import traceback

suite = unittest.TestSuite()
suite.addTest(test_offline_bundle_adversarial.TestOfflineBundleAdversarial('test_simulated_worker_blob_lifecycle_and_frame_decoding'))
try:
    test = test_offline_bundle_adversarial.TestOfflineBundleAdversarial('test_simulated_worker_blob_lifecycle_and_frame_decoding')
    test.setUpClass()
    test.test_simulated_worker_blob_lifecycle_and_frame_decoding()
    print("SUCCESS")
except Exception as e:
    traceback.print_exc()
