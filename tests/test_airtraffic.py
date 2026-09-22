import unittest
from unittest.mock import Mock, patch

from aircard import airtraffic


class AirTrafficSupervisorTests(unittest.TestCase):
    def test_hard_timeout_terminates_blocked_worker(self):
        events = Mock()
        process = Mock()
        process.is_alive.side_effect = [True, False]
        context = Mock()
        context.Queue.return_value = events
        context.Process.return_value = process

        with (
            patch.object(airtraffic.multiprocessing, "get_context", return_value=context),
            patch.object(airtraffic.time, "monotonic", side_effect=[0.0, 6.0]),
        ):
            with self.assertRaisesRegex(airtraffic.AirTrafficError, "设备同步超时"):
                airtraffic.sync_assets_via_airtraffic(
                    "device", [("source", "destination")], timeout_sec=5
                )

        process.start.assert_called_once()
        process.terminate.assert_called_once()
        events.cancel_join_thread.assert_called_once()
        events.close.assert_called_once()

    def test_empty_asset_list_does_not_start_worker(self):
        with patch.object(airtraffic.multiprocessing, "get_context") as get_context:
            self.assertTrue(airtraffic.sync_assets_via_airtraffic("device", []))
        get_context.assert_not_called()


if __name__ == "__main__":
    unittest.main()
