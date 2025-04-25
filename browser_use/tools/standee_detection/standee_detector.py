import logging
import os
import sys
import requests
from pathlib import Path
from typing import Dict, List, Union, Optional, Any, Tuple

class StandeeDetectionTool:
    """Tool for detecting standees in images using YOLOv8."""
    
    def __init__(self, model_path: Optional[str] = None, confidence_threshold: float = 0.25):
        """
        Initialize standee detection tool.
        
        Args:
            model_path: Path to YOLOv8 model. If None, will try to find it in default locations.
            confidence_threshold: Minimum confidence for detection.
        """
        self.logger = logging.getLogger(__name__)
        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self._model = None
        
    def load_model(self):
        """Load YOLOv8 model from path."""
        if self._model is not None:
            return self._model
            
        try:
            import torch
            from ultralytics import YOLO
            
            if self.model_path is None:
                potential_paths = [
                    Path(os.getcwd()) / "models" / "yolov8" / "runs" / "standee_detection_train" / "weights" / "best.pt",
                    Path("/home/ubuntu/repos/naver-cf-search/models/yolov8/runs/standee_detection_train/weights/best.pt"),
                ]
                
                for path in potential_paths:
                    if path.exists():
                        self.model_path = str(path)
                        self.logger.info(f"Found model at: {self.model_path}")
                        break
                        
            if self.model_path is None or not Path(self.model_path).exists():
                self.logger.error(f"Model not found at {self.model_path}")
                return None
                
            self.logger.info(f"Loading model from: {self.model_path}")
            self._model = YOLO(self.model_path)
            self._model.to('cpu')
            
            self._model.overrides = {
                'conf': self.confidence_threshold,
                'iou': 0.45,
                'max_det': 50,
                'agnostic_nms': True,
                'task': 'segment',
                'mode': 'predict',
                'imgsz': 640,
                'device': 'cpu'
            }
            
            self.logger.info("Model loaded successfully")
            return self._model
            
        except Exception as e:
            self.logger.error(f"Error loading model: {str(e)}")
            return None
            
    def detect_from_url(self, image_url: str) -> Dict[str, Any]:
        """Detect standees in an image from URL."""
        try:
            response = requests.get(image_url)
            if response.status_code != 200:
                return {'success': False, 'error': f'Failed to download image: {response.status_code}'}
                
            return self.detect_from_bytes(response.content)
        except Exception as e:
            return {'success': False, 'error': f'Error detecting from URL: {str(e)}'}
            
    def detect_from_bytes(self, image_bytes: bytes) -> Dict[str, Any]:
        """Detect standees in image bytes."""
        try:
            try:
                sys.path.append("/home/ubuntu/repos/naver-cf-search")
                from yolo_bridge import detect_standees_bytes
                
                result = detect_standees_bytes(image_bytes)
                return result
            except ImportError:
                self.logger.info("yolo_bridge module not found, using local implementation")
                return self._detect_standees_bytes_local(image_bytes)
        except Exception as e:
            return {'success': False, 'error': f'Error in detect_from_bytes: {str(e)}'}
            
    def _detect_standees_bytes_local(self, image_bytes: bytes) -> Dict[str, Any]:
        """Local implementation of detect_standees_bytes if yolo_bridge is not available."""
        if image_bytes is None:
            return {'success': False, 'error': 'Image bytes cannot be None'}
            
        model = self.load_model()
        if model is None:
            return {'success': False, 'error': 'Model initialization failed'}
            
        try:
            import cv2
            import numpy as np
            
            np_arr = np.frombuffer(image_bytes, np.uint8)
            img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img is None:
                return {'success': False, 'error': 'Failed to decode image bytes'}
                
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            lab_planes = cv2.split(lab)
            lab_planes[0] = clahe.apply(lab_planes[0])
            lab = cv2.merge(lab_planes)
            img = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
                
            results = model.predict(
                img,
                conf=self.confidence_threshold,
                iou=0.10,
                agnostic_nms=True,
                max_det=500,
                verbose=False
            )
            
            detections = []
            
            if len(results) > 0:
                result = results[0]
                
                if hasattr(result, 'boxes') and len(result.boxes) > 0:
                    boxes = result.boxes
                    
                    for i, box in enumerate(boxes):
                        try:
                            x1, y1, x2, y2 = box.xyxy[0].tolist()
                            
                            confidence = box.conf[0].item()
                            
                            cls = int(box.cls[0].item())
                            
                            detection = {
                                'box': [x1, y1, x2, y2],
                                'confidence': confidence,
                                'class': cls,
                                'width': x2 - x1,
                                'height': y2 - y1,
                                'area': (x2 - x1) * (y2 - y1),
                                'aspect_ratio': (x2 - x1) / (y2 - y1) if (y2 - y1) > 0 else 0
                            }
                            
                            if self._meets_standee_criteria(detection, img.shape):
                                detections.append(detection)
                                
                        except Exception as e:
                            self.logger.error(f"Error processing detection {i}: {str(e)}")
            
            return {
                'success': True,
                'detections': detections,
                'count': len(detections)
            }
            
        except Exception as e:
            return {'success': False, 'error': f'Detection failed: {str(e)}'}
            
    def _meets_standee_criteria(self, detection: Dict[str, Any], img_shape: Tuple[int, int, int]) -> bool:
        """
        Simplified version of meets_standee_criteria from yolo_bridge.
        Determines if a detection meets the criteria for being a standee.
        """
        img_height, img_width = img_shape[:2]
        
        box = detection['box']
        confidence = detection['confidence']
        width = detection['width']
        height = detection['height']
        aspect_ratio = detection['aspect_ratio']
        
        min_width_ratio = 0.05  # Minimum width as percentage of image width
        min_height_ratio = 0.1  # Minimum height as percentage of image height
        
        if width < img_width * min_width_ratio or height < img_height * min_height_ratio:
            return False
            
        if aspect_ratio > 1.0:  # Width > Height
            return False
            
        if confidence < self.confidence_threshold:
            return False
            
        return True
