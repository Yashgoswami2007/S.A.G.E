import unittest
from unittest.mock import patch, MagicMock
from sage.models.gpu_detector import detect_gpus, GPUStatus, GPUInfo, _parse_nvidia_smi

class TestGPUDetector(unittest.TestCase):
    def setUp(self):
        # Reset the singleton cache before each test
        import sage.models.gpu_detector as detector
        detector._cached_status = None

    @patch("subprocess.run")
    def test_parse_nvidia_smi_success(self, mock_run):
        """Test successful parsing of nvidia-smi CSV output."""
        # We need to mock 3 subprocess calls in order: 
        # 1. The main query
        # 2. Driver version query
        # 3. Header query (for CUDA version)
        
        main_mock = MagicMock()
        main_mock.returncode = 0
        main_mock.stdout = "0, NVIDIA GeForce RTX 3060, 12288, 10240\n"
        
        driver_mock = MagicMock()
        driver_mock.returncode = 0
        driver_mock.stdout = "560.35.03\n"
        
        header_mock = MagicMock()
        header_mock.returncode = 0
        header_mock.stdout = "| NVIDIA-SMI 560.35.03    Driver Version: 560.35.03    CUDA Version: 12.6  |\n"
        
        mock_run.side_effect = [main_mock, driver_mock, header_mock]

        status = _parse_nvidia_smi()

        self.assertIsNotNone(status)
        self.assertTrue(status.cuda_available)
        self.assertEqual(status.gpu_count, 1)
        self.assertEqual(status.driver_version, "560.35.03")
        self.assertEqual(status.cuda_version, "12.6")
        
        gpu = status.gpus[0]
        self.assertEqual(gpu.gpu_index, 0)
        self.assertEqual(gpu.name, "NVIDIA GeForce RTX 3060")
        self.assertEqual(gpu.vram_total_mb, 12288)
        self.assertEqual(gpu.vram_free_mb, 10240)
        self.assertEqual(gpu.driver_version, "560.35.03")
        self.assertEqual(gpu.cuda_version, "12.6")

    @patch("subprocess.run")
    def test_parse_nvidia_smi_not_found(self, mock_run):
        """Test graceful fallback when nvidia-smi is not installed."""
        mock_run.side_effect = FileNotFoundError()
        
        status = _parse_nvidia_smi()
        self.assertIsNone(status)

    @patch("subprocess.run")
    def test_parse_nvidia_smi_error(self, mock_run):
        """Test graceful fallback when nvidia-smi fails to run."""
        mock_error = MagicMock()
        mock_error.returncode = 1
        mock_error.stderr = "Command not found"
        mock_run.return_value = mock_error
        
        status = _parse_nvidia_smi()
        self.assertIsNone(status)

    @patch("sage.models.gpu_detector._parse_nvidia_smi")
    def test_detect_gpus_caching(self, mock_parse):
        """Test that detect_gpus caches the result."""
        mock_status = GPUStatus(
            cuda_available=True, gpu_count=1, driver_version="1", cuda_version="1",
            gpus=[GPUInfo(gpu_index=0, name="test", vram_total_mb=1, vram_free_mb=1, driver_version="1", cuda_version="1")]
        )
        mock_parse.return_value = mock_status
        
        # First call should invoke parse
        res1 = detect_gpus()
        self.assertEqual(res1.cuda_available, True)
        mock_parse.assert_called_once()
        
        # Second call should use cache
        res2 = detect_gpus()
        self.assertEqual(res2.cuda_available, True)
        mock_parse.assert_called_once() # Call count shouldn't increase
        
        # Forced refresh
        res3 = detect_gpus(force_refresh=True)
        self.assertEqual(mock_parse.call_count, 2)

    @patch("sage.models.gpu_detector._parse_nvidia_smi")
    def test_detect_gpus_none_fallback(self, mock_parse):
        """Test that detect_gpus converts None from parser into a valid empty status."""
        mock_parse.return_value = None
        
        status = detect_gpus(force_refresh=True)
        self.assertFalse(status.cuda_available)
        self.assertEqual(status.gpu_count, 0)
        self.assertEqual(len(status.gpus), 0)

if __name__ == "__main__":
    unittest.main()
