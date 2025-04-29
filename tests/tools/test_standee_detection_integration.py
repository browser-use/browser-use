import sys
import os
import unittest
import importlib.util
from pathlib import Path
from unittest.mock import patch, MagicMock
import numpy as np

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from browser_use.tools.standee_detection import StandeeDetectionTool


class TestStandeeDetectionIntegration(unittest.TestCase):
    """Integration tests for the standee detection tool with YOLOv8 model."""

    def setUp(self):
        """Set up the test environment."""
        naver_cf_search_path = "/home/ubuntu/repos/naver-cf-search"
        if naver_cf_search_path not in sys.path:
            sys.path.append(naver_cf_search_path)
        
        self.model_path = Path(naver_cf_search_path) / "models" / "yolov8" / "runs" / "standee_detection_train" / "weights" / "best.pt"
        self.assertTrue(self.model_path.exists(), f"YOLOv8 model not found at {self.model_path}")
        
        self.tool = StandeeDetectionTool(model_path=str(self.model_path))
        
        self.ultralytics_installed = importlib.util.find_spec("ultralytics") is not None
        if not self.ultralytics_installed:
            print("WARNING: ultralytics package is not installed. Some tests will be skipped.")

    def test_model_loading(self):
        """Test that the YOLOv8 model can be loaded."""
        if not self.ultralytics_installed:
            self.skipTest("ultralytics package is not installed")
            
        model = self.tool.load_model()
        self.assertIsNotNone(model, "Failed to load YOLOv8 model")
        self.assertEqual(str(self.model_path), self.tool.model_path)

    @patch('cv2.imdecode')
    @patch('numpy.frombuffer')
    def test_detect_from_bytes_with_yolo_bridge(self, mock_frombuffer, mock_imdecode):
        """Test detection using the yolo_bridge module."""
        mock_img = np.zeros((640, 640, 3), dtype=np.uint8)
        mock_imdecode.return_value = mock_img
        mock_frombuffer.return_value = np.zeros(1, dtype=np.uint8)
        
        with patch.dict('sys.modules', {'yolo_bridge': MagicMock()}):
            from yolo_bridge import detect_standees_bytes
            
            detect_standees_bytes.return_value = {
                'success': True,
                'detections': [
                    {
                        'confidence': 0.85,
                        'bbox': [0.1, 0.2, 0.3, 0.4],
                        'segmentation': {
                            'points': [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
                            'point_count': 3
                        },
                        'image_height': 640
                    }
                ]
            }
            
            result = self.tool.detect_from_bytes(b'test_image_data')
            
            self.assertTrue(result['success'])
            self.assertIn('detections', result)
            detect_standees_bytes.assert_called_once_with(b'test_image_data')

    def test_detect_from_bytes_local_implementation(self):
        """Test the local implementation of detect_from_bytes."""
        test_image = np.zeros((640, 640, 3), dtype=np.uint8)
        test_image[100:300, 200:400] = 255  # Add a white rectangle
        
        import cv2
        _, image_bytes = cv2.imencode('.jpg', test_image)
        image_bytes = image_bytes.tobytes()
        
        with patch.dict('sys.modules', {'yolo_bridge': None}):
            with patch.object(self.tool, '_detect_standees_bytes_local') as mock_detect_local:
                mock_detect_local.return_value = {
                    'success': True,
                    'detections': [
                        {
                            'box': [200, 100, 400, 300],
                            'confidence': 0.85,
                            'class': 0,
                            'width': 200,
                            'height': 200,
                            'area': 40000,
                            'aspect_ratio': 1.0
                        }
                    ],
                    'count': 1
                }
                
                result = self.tool.detect_from_bytes(image_bytes)
                
                self.assertTrue(result['success'])
                self.assertIn('detections', result)
                self.assertEqual(1, result.get('count', 0))
                mock_detect_local.assert_called_once_with(image_bytes)

    def test_model_configuration(self):
        """Test that the model is configured correctly."""
        if not self.ultralytics_installed:
            self.skipTest("ultralytics package is not installed")
            
        model = self.tool.load_model()
        self.assertIsNotNone(model)
        
        self.assertEqual(self.tool.confidence_threshold, model.overrides['conf'])
        self.assertEqual(0.45, model.overrides['iou'])
        self.assertEqual(50, model.overrides['max_det'])
        self.assertTrue(model.overrides['agnostic_nms'])
        self.assertEqual('segment', model.overrides['task'])
        self.assertEqual('predict', model.overrides['mode'])
        self.assertEqual(640, model.overrides['imgsz'])
        self.assertEqual('cpu', model.overrides['device'])
        
    def test_model_path_verification(self):
        """Test that the model path is correctly verified."""
        self.assertEqual(str(self.model_path), self.tool.model_path)
        self.assertTrue(Path(self.tool.model_path).exists())
        
        non_existent_tool = StandeeDetectionTool(model_path="/non/existent/path.pt")
        self.assertIsNone(non_existent_tool.load_model())


if __name__ == '__main__':
    unittest.main()
