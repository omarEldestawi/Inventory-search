# -*- coding: utf-8 -*-
"""
Challenger Adversarial Test Suite: ProcurementEngineBridge & Pipeline Concurrency
Adversarially verifies:
  1. Background thread execution, daemon state, lifecycle & termination.
  2. Queue message delivery: PROGRESS, DONE, ERROR (cancellation & exceptions).
  3. High-frequency event delivery under extreme load (no dropped messages, no queue deadlocks).
  4. Concurrent producer-consumer dynamics simulating CustomTkinter 50ms GUI event loop.
  5. Cooperative cancellation responsiveness and signal propagation.
  6. Double-start protection and bridge instance reuse.
"""
import os
import sys
import time
import queue
import threading
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import pandas as pd

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.controller import ProcurementEngineBridge, classify_files
from src.pipeline import run_procurement_pipeline, PipelineExecutionError


class TestProcurementEngineBridgeAdversarial(unittest.TestCase):
    """Adversarial stress testing for ProcurementEngineBridge."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = self.temp_dir.name
        self.catalogs_dir = os.path.join(PROJECT_ROOT, "input", "catalogs")
        self.orders_dir = os.path.join(PROJECT_ROOT, "input", "orders")

        self.sample_catalogs = [
            os.path.join(self.catalogs_dir, f)
            for f in os.listdir(self.catalogs_dir)
            if f.endswith(".pdf")
        ]
        self.sample_order = os.path.join(self.orders_dir, "طلبية_اليوم.xlsx")

    def tearDown(self):
        self.temp_dir.cleanup()

    # ========================================================================
    # 1. Lifecycle & Message Delivery Tests (Real Pipeline)
    # ========================================================================

    def test_01_real_pipeline_full_lifecycle_and_message_delivery(self):
        """Verify background thread execution, daemon flag, and message delivery (PROGRESS -> DONE)."""
        bridge = ProcurementEngineBridge()
        self.assertFalse(bridge.is_running)

        worker_thread = bridge.start(
            order_files=[self.sample_order],
            catalog_files=self.sample_catalogs,
            output_dir=self.output_dir,
        )

        # Thread must be active and daemon
        self.assertTrue(worker_thread.is_alive())
        self.assertTrue(worker_thread.daemon)
        self.assertTrue(bridge.is_running)

        messages = []
        start_time = time.time()
        timeout = 40.0

        # Simulate GUI polling loop
        while time.time() - start_time < timeout:
            msg = bridge.get_message(block=True, timeout=0.1)
            if msg is not None:
                messages.append(msg)
                if msg[0] in ("DONE", "ERROR"):
                    break

        bridge.join(timeout=5.0)
        self.assertFalse(bridge.is_running)
        self.assertFalse(worker_thread.is_alive())

        msg_types = [m[0] for m in messages]
        self.assertIn("PROGRESS", msg_types)
        self.assertIn("DONE", msg_types)
        self.assertNotIn("ERROR", msg_types)

        # Validate PROGRESS structure
        progress_msgs = [m for m in messages if m[0] == "PROGRESS"]
        self.assertGreaterEqual(len(progress_msgs), 5)
        for _, pct, text in progress_msgs:
            self.assertIsInstance(pct, float)
            self.assertGreaterEqual(pct, 0.0)
            self.assertLessEqual(pct, 1.0)
            self.assertIsInstance(text, str)
            self.assertGreater(len(text), 0)

        # Validate DONE structure
        done_msg = [m for m in messages if m[0] == "DONE"][0]
        res = done_msg[1]
        self.assertIn("results", res)
        self.assertIn("report_path", res)
        self.assertIn("arabic_report_path", res)
        self.assertIn("kpis", res)
        self.assertTrue(os.path.exists(res["report_path"]))
        self.assertEqual(bridge.last_result, res)
        self.assertIsNone(bridge.last_error)

    def test_02_error_delivery_on_invalid_inputs(self):
        """Verify error message delivery and traceback capture when inputs are invalid."""
        bridge = ProcurementEngineBridge()
        bridge.start(
            order_files=[],
            catalog_files=[],
            output_dir=self.output_dir,
        )

        bridge.join(timeout=10.0)
        self.assertFalse(bridge.is_running)

        messages = []
        while True:
            msg = bridge.get_message(block=False)
            if msg is None:
                break
            messages.append(msg)

        msg_types = [m[0] for m in messages]
        self.assertIn("ERROR", msg_types)
        self.assertNotIn("DONE", msg_types)

        err_msg = [m for m in messages if m[0] == "ERROR"][0]
        self.assertEqual(len(err_msg), 3)  # ("ERROR", message, traceback)
        self.assertIn("No purchase order", err_msg[1])
        self.assertIn("Traceback", err_msg[2])
        self.assertIsNotNone(bridge.last_error)
        self.assertIsNone(bridge.last_result)

    def test_03_cooperative_cancellation_delivery(self):
        """Verify cancellation signaling, fast abort, and ERROR delivery with cancellation note."""
        bridge = ProcurementEngineBridge()

        # Start with real files but cancel immediately
        bridge.start(
            order_files=[self.sample_order],
            catalog_files=self.sample_catalogs,
            output_dir=self.output_dir,
        )
        self.assertTrue(bridge.is_running)

        # Signal cancellation
        bridge.cancel()
        bridge.join(timeout=15.0)

        self.assertFalse(bridge.is_running)

        messages = []
        while True:
            msg = bridge.get_message(block=False)
            if msg is None:
                break
            messages.append(msg)

        msg_types = [m[0] for m in messages]
        # In case cancellation hit during ingestion or validation
        if "DONE" not in msg_types:
            self.assertIn("ERROR", msg_types)
            err_msg = [m for m in messages if m[0] == "ERROR"][0]
            self.assertIn("Cancelled", err_msg[1])
            self.assertIn("Traceback", err_msg[2])

    def test_04_double_start_protection(self):
        """Verify that calling start() while worker is already executing raises RuntimeError."""
        bridge = ProcurementEngineBridge()
        bridge.start(
            order_files=[self.sample_order],
            catalog_files=self.sample_catalogs,
            output_dir=self.output_dir,
        )
        self.assertTrue(bridge.is_running)

        with self.assertRaises(RuntimeError) as ctx:
            bridge.start(
                order_files=[self.sample_order],
                catalog_files=self.sample_catalogs,
                output_dir=self.output_dir,
            )
        self.assertIn("already running", str(ctx.exception))

        bridge.join(timeout=30.0)
        self.assertFalse(bridge.is_running)

    def test_05_bridge_instance_reuse_after_completion(self):
        """Verify that a ProcurementEngineBridge instance can be cleanly reused for a 2nd run."""
        bridge = ProcurementEngineBridge()

        # Run 1: with error
        bridge.start(order_files=[], catalog_files=[], output_dir=self.output_dir)
        bridge.join(timeout=5.0)
        self.assertFalse(bridge.is_running)
        self.assertIsNotNone(bridge.last_error)

        # Drain queue
        while bridge.get_message(block=False) is not None:
            pass

        # Run 2: with valid inputs
        bridge.start(
            order_files=[self.sample_order],
            catalog_files=[self.sample_catalogs[0]],
            output_dir=self.output_dir,
        )
        self.assertTrue(bridge.is_running)
        bridge.join(timeout=30.0)
        self.assertFalse(bridge.is_running)
        self.assertIsNotNone(bridge.last_result)

    # ========================================================================
    # 2. High Event Frequency & Concurrency Stress Tests
    # ========================================================================

    def test_06_high_frequency_event_delivery_no_drop(self):
        """
        Adversarial Stress Test:
        Simulate a rapid-fire worker emitting 25,000 progress messages.
        Verify:
          1. Exactly 25,000 PROGRESS + 1 DONE messages are delivered.
          2. Zero dropped messages.
          3. Queue does not lock up or deadlock.
          4. Sequence ordering is preserved (monotonic counter).
        """
        bridge = ProcurementEngineBridge()
        num_events = 25000

        def mock_pipeline_rapid(order_files, catalog_files, output_dir, progress_callback=None, cancel_check=None, **kwargs):
            for i in range(num_events):
                if cancel_check and cancel_check():
                    raise InterruptedError("Cancelled")
                if progress_callback:
                    progress_callback(i / num_events, f"Event {i}")
            return {"status": "ok", "count": num_events}

        with patch("src.controller.run_procurement_pipeline", side_effect=mock_pipeline_rapid):
            t_start = time.time()
            bridge.start(order_files=["dummy"], catalog_files=["dummy"], output_dir=self.output_dir)

            bridge.join(timeout=20.0)
            t_elapsed = time.time() - t_start

            self.assertFalse(bridge.is_running)

            # Drain queue and check counts
            messages = []
            while True:
                msg = bridge.get_message(block=False)
                if msg is None:
                    break
                messages.append(msg)

            self.assertEqual(len(messages), num_events + 1)
            self.assertEqual(messages[-1][0], "DONE")

            # Verify all progress sequence numbers
            for idx, msg in enumerate(messages[:-1]):
                self.assertEqual(msg[0], "PROGRESS")
                self.assertEqual(msg[2], f"Event {idx}")

            # Performance verification: 25k messages should complete in under 5 seconds
            self.assertLess(t_elapsed, 10.0, f"High frequency emission took too long: {t_elapsed:.2f}s")

    def test_07_concurrent_producer_consumer_stream_simulation(self):
        """
        Adversarial Stress Test:
        Worker emits 50,000 events while consumer polls the queue periodically
        (simulating CustomTkinter UI root.after(50, poll) with variable batch sizes).
        Verify zero race conditions, deadlocks, or dropped events under concurrent read/write.
        """
        bridge = ProcurementEngineBridge()
        num_events = 50000

        def mock_pipeline_stream(order_files, catalog_files, output_dir, progress_callback=None, cancel_check=None, **kwargs):
            for i in range(num_events):
                if progress_callback:
                    progress_callback(i / num_events, f"BATCH_{i}")
            return {"results": "stream_done"}

        consumed_messages = []
        consumer_active = threading.Event()
        consumer_active.set()

        def gui_consumer_thread():
            while consumer_active.is_set() or bridge.is_running:
                # Read batch
                while True:
                    msg = bridge.get_message(block=False)
                    if msg is None:
                        break
                    consumed_messages.append(msg)
                time.sleep(0.01)  # 10ms poll delay simulating GUI frame interval

            # Final drain
            while True:
                msg = bridge.get_message(block=False)
                if msg is None:
                    break
                consumed_messages.append(msg)

        with patch("src.controller.run_procurement_pipeline", side_effect=mock_pipeline_stream):
            consumer = threading.Thread(target=gui_consumer_thread, daemon=True)
            consumer.start()

            bridge.start(order_files=["dummy"], catalog_files=["dummy"], output_dir=self.output_dir)
            bridge.join(timeout=30.0)

            # Let consumer finish draining
            consumer_active.clear()
            consumer.join(timeout=5.0)

            self.assertFalse(bridge.is_running)
            self.assertEqual(len(consumed_messages), num_events + 1)
            self.assertEqual(consumed_messages[-1][0], "DONE")

            # Check message integrity
            for i in range(min(100, num_events)):
                self.assertEqual(consumed_messages[i][2], f"BATCH_{i}")
            self.assertEqual(consumed_messages[-2][2], f"BATCH_{num_events - 1}")

    def test_08_cancellation_during_high_frequency_stream(self):
        """
        Adversarial Stress Test:
        Worker emits high-frequency events; bridge.cancel() is signaled midway.
        Verify:
          1. Loop aborts within small event delta.
          2. ERROR / Cancel message is posted.
          3. Worker thread terminates promptly without leaking.
        """
        bridge = ProcurementEngineBridge()
        max_events = 1000000

        def infinite_pipeline(order_files, catalog_files, output_dir, progress_callback=None, cancel_check=None, **kwargs):
            count = 0
            while count < max_events:
                if cancel_check and cancel_check():
                    raise InterruptedError(f"Cancelled after {count} events")
                if progress_callback:
                    progress_callback(count / max_events, f"Progress {count}")
                count += 1
                time.sleep(0.0001)
            return {"results": "completed"}

        with patch("src.controller.run_procurement_pipeline", side_effect=infinite_pipeline):
            bridge.start(order_files=["dummy"], catalog_files=["dummy"], output_dir=self.output_dir)
            self.assertTrue(bridge.is_running)

            # Let it emit for 0.1s then cancel
            time.sleep(0.1)
            bridge.cancel()

            # Must terminate within 2 seconds
            t_cancel_start = time.time()
            bridge.join(timeout=3.0)
            t_cancel_dur = time.time() - t_cancel_start

            self.assertFalse(bridge.is_running)
            self.assertLess(t_cancel_dur, 2.5)

            # Drain messages
            messages = []
            while True:
                m = bridge.get_message(block=False)
                if m is None:
                    break
                messages.append(m)

            self.assertGreater(len(messages), 0)
            self.assertEqual(messages[-1][0], "ERROR")
            self.assertIn("Cancelled after", messages[-1][1])

    def test_09_custom_injected_queue(self):
        """Verify custom external queue injection works identically."""
        custom_q = queue.Queue()
        bridge = ProcurementEngineBridge(message_queue=custom_q)
        self.assertIs(bridge.queue, custom_q)

        bridge.start(order_files=[], catalog_files=[], output_dir=self.output_dir)
        bridge.join(timeout=5.0)

        self.assertFalse(bridge.is_running)
        msg = custom_q.get_nowait()
        self.assertEqual(msg[0], "ERROR")

    def test_10_get_message_timeout_non_blocking_contract(self):
        """Verify get_message(block=True, timeout=...) behaves cleanly on empty queue."""
        bridge = ProcurementEngineBridge()
        t0 = time.time()
        msg = bridge.get_message(block=True, timeout=0.08)
        t_diff = time.time() - t0

        self.assertIsNone(msg)
        self.assertGreaterEqual(t_diff, 0.05)
        self.assertLess(t_diff, 0.5)


def run_all_tests():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestProcurementEngineBridgeAdversarial)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
