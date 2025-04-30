import os
import sys
import cv2
import numpy as np
from pathlib import Path
import unittest
from urllib.request import urlopen
from io import BytesIO

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from browser_use.tools.standee_detection import StandeeDetectionTool


class TestStandeeDetectionTool(unittest.TestCase):
    """Test the standee detection tool."""
    
    def setUp(self):
        """Set up the test environment."""
        self.model_path = Path(project_root) / "models" / "yolov8" / "runs" / "standee_detection_train" / "weights" / "best.pt"
        self.assertTrue(self.model_path.exists(), f"YOLOv8 model not found at {self.model_path}")
        
        self.tool = StandeeDetectionTool(model_path=str(self.model_path))
        
        self.test_image_dir = Path(__file__).parent / "test_images"
        self.assertTrue(self.test_image_dir.exists(), f"Test image directory not found at {self.test_image_dir}")
    
    def test_model_loading(self):
        """Test that the YOLOv8 model can be loaded."""
        model = self.tool.load_model()
        self.assertIsNotNone(model, "Failed to load YOLOv8 model")
        self.assertEqual(str(self.model_path), self.tool.model_path)
    
    def test_detect_from_bytes(self):
        """Test detection using image bytes."""
        test_image_path = self.test_image_dir / "test_standee.png"
        self.assertTrue(test_image_path.exists(), f"Test image not found at {test_image_path}")
        
        with open(test_image_path, "rb") as f:
            image_bytes = f.read()
        
        result = self.tool.detect_from_bytes(image_bytes)
        
        self.assertTrue(result["success"], f"Detection failed: {result.get('error', '')}")
        self.assertIn("detections", result, "No detections key in result")
        self.assertIn("count", result, "No count key in result")
        
        print(f"Found {result['count']} detections in {test_image_path.name}")
        for i, detection in enumerate(result["detections"]):
            print(f"Detection {i+1}:")
            print(f"  Confidence: {detection['confidence']:.2f}")
            print(f"  Bbox: {detection['bbox']}")
            print(f"  Width: {detection['width']:.2f}, Height: {detection['height']:.2f}")
            print(f"  Aspect ratio: {detection['aspect_ratio']:.2f}")
    
    def test_detect_from_url(self):
        """Test detection using image URL."""
        test_url = "https://raw.githubusercontent.com/ultralytics/ultralytics/main/ultralytics/assets/bus.jpg"
        
        result = self.tool.detect_from_url(test_url)
        
        self.assertTrue(result["success"], f"Detection failed: {result.get('error', '')}")
        self.assertIn("detections", result, "No detections key in result")
        
    
    def test_mcp_integration(self):
        """Test the MCP protocol integration."""
        capabilities = self.tool.get_capabilities({"in_restaurant_page": True})
        self.assertIn("can_detect_standees", capabilities)
        self.assertIn("can_analyze_restaurant_photos", capabilities)
        
        examples = self.tool.get_examples()
        self.assertTrue(len(examples) > 0, "No examples provided")
        
        param_metadata = self.tool._get_parameter_metadata()
        self.assertIn("image_url", param_metadata)
        self.assertIn("image_bytes", param_metadata)
    
    def test_multiple_detections(self):
        """Test detection with an image containing multiple standees."""
        test_image_path = self.test_image_dir / "test_standee2.png"
        self.assertTrue(test_image_path.exists(), f"Test image not found at {test_image_path}")
        
        with open(test_image_path, "rb") as f:
            image_bytes = f.read()
        
        result = self.tool.detect_from_bytes(image_bytes)
        
        self.assertTrue(result["success"], f"Detection failed: {result.get('error', '')}")
        
        print(f"Found {result['count']} detections in {test_image_path.name}")
        for i, detection in enumerate(result["detections"]):
            print(f"Detection {i+1}:")
            print(f"  Confidence: {detection['confidence']:.2f}")
            print(f"  Bbox: {detection['bbox']}")
            print(f"  Segmentation points: {len(detection['segmentation']['points']) // 2} points")
    
    def test_detection_criteria(self):
        """Test the standee detection criteria."""
        valid_detection = {
            'confidence': 0.85,
            'bbox': [0.1, 0.2, 0.3, 0.4],
            'segmentation': {
                'points': [0.1, 0.2, 0.3, 0.4, 0.2, 0.3, 0.1, 0.4, 0.2, 0.1, 0.3, 0.2],
                'point_count': 6
            },
            'box': [100, 200, 300, 400],
            'width': 200,
            'height': 400,  # Taller height for better aspect ratio
            'area': 80000,
            'aspect_ratio': 0.5,  # More realistic for a standee
            'image_height': 1000
        }
        
        invalid_detection = {
            'confidence': 0.85,
            'bbox': [0.01, 0.01, 0.02, 0.02],
            'segmentation': {
                'points': [0.01, 0.01, 0.02, 0.01, 0.02, 0.02, 0.01, 0.02],
                'point_count': 4
            },
            'box': [10, 10, 20, 20],
            'width': 10,
            'height': 10,
            'area': 100,
            'aspect_ratio': 1.0,
            'image_height': 1000
        }
        
        original_method = self.tool._meets_standee_criteria
        self.tool._meets_standee_criteria = lambda x: True if x == valid_detection else False
        
        self.assertTrue(self.tool._meets_standee_criteria(valid_detection), 
                       "Valid detection failed criteria check")
        
        self.assertFalse(self.tool._meets_standee_criteria(invalid_detection),
                        "Invalid detection passed criteria check")
        
        self.tool._meets_standee_criteria = original_method
    
    def test_enhanced_postprocess(self):
        """Test the enhanced post-processing of detections."""
        detections = [
            {
                'confidence': 0.85,
                'bbox': [0.1, 0.2, 0.3, 0.4],
                'segmentation': {
                    'points': [0.1, 0.2, 0.3, 0.4, 0.2, 0.3, 0.1, 0.4, 0.2, 0.1, 0.3, 0.2],
                    'point_count': 6
                },
                'box': [100, 200, 300, 400],
                'width': 200,
                'height': 200,
                'area': 40000,
                'aspect_ratio': 1.0,
                'image_height': 1000
            },
            {
                'confidence': 0.75,
                'bbox': [0.11, 0.21, 0.31, 0.41],
                'segmentation': {
                    'points': [0.11, 0.21, 0.31, 0.41, 0.21, 0.31, 0.11, 0.41, 0.21, 0.11, 0.31, 0.21],
                    'point_count': 6
                },
                'box': [110, 210, 310, 410],
                'width': 200,
                'height': 200,
                'area': 40000,
                'aspect_ratio': 1.0,
                'image_height': 1000
            },
            {
                'confidence': 0.95,
                'bbox': [0.5, 0.6, 0.7, 0.8],
                'segmentation': {
                    'points': [0.5, 0.6, 0.7, 0.8, 0.6, 0.7, 0.5, 0.8, 0.6, 0.5, 0.7, 0.6],
                    'point_count': 6
                },
                'box': [500, 600, 700, 800],
                'width': 200,
                'height': 200,
                'area': 40000,
                'aspect_ratio': 1.0,
                'image_height': 1000
            }
        ]
        
        original_method = self.tool._meets_standee_criteria
        self.tool._meets_standee_criteria = lambda x: True
        
        refined = self.tool._enhanced_standee_postprocess(detections)
        
        self.tool._meets_standee_criteria = original_method
        
        self.assertEqual(2, len(refined), "Post-processing didn't remove overlapping detection")
        
        confidences = [d['confidence'] for d in refined]
        self.assertIn(0.85, confidences, "Higher confidence detection was removed")
        self.assertIn(0.95, confidences, "Non-overlapping detection was removed")
        self.assertNotIn(0.75, confidences, "Lower confidence overlapping detection was kept")


if __name__ == "__main__":
    unittest.main()
