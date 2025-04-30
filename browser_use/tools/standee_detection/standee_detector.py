import logging
import os
import sys
import requests
import numpy as np
import cv2
from pathlib import Path
from typing import Dict, Optional, Any, Tuple, List

from ..mcp_protocol import MCPToolBase


class StandeeDetectionTool(MCPToolBase):
    """Tool for detecting standees in images using YOLOv8."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        confidence_threshold: float = 0.25
    ):
        """
        Initialize standee detection tool.

        Args:
            model_path: Path to YOLOv8 model. If None, will try to find it in
                default locations.
            confidence_threshold: Minimum confidence for detection.
        """
        super().__init__(
            name="standee_detection",
            description="Detects standees (promotional cardboard cutouts) in images using YOLOv8"
        )
        self.logger = logging.getLogger(__name__)
        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self._model = None

    def load_model(self):
        """Load YOLOv8 model from path."""
        if self._model is not None:
            return self._model

        try:
            from ultralytics import YOLO

            if self.model_path is None:
                potential_paths = [
                    Path(os.path.dirname(os.path.abspath(__file__)))
                    / "../../../models"
                    / "yolov8"
                    / "runs"
                    / "standee_detection_train"
                    / "weights"
                    / "best.pt",
                    Path(os.getcwd())
                    / "models"
                    / "yolov8"
                    / "runs"
                    / "standee_detection_train"
                    / "weights"
                    / "best.pt",
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
                return {
                    'success': False,
                    'error': (
                        f'Failed to download image: {response.status_code}'
                    )
                }

            return self.detect_from_bytes(response.content)
        except Exception as e:
            return {
                'success': False,
                'error': f'Error detecting from URL: {str(e)}'
            }

    def detect_from_bytes(self, image_bytes: bytes) -> Dict[str, Any]:
        """Detect standees in image bytes."""
        try:
            return self._detect_standees_bytes_local(image_bytes)
        except Exception as e:
            return {
                'success': False,
                'error': f'Error in detect_from_bytes: {str(e)}'
            }

    def _detect_standees_bytes_local(
        self, image_bytes: bytes
    ) -> Dict[str, Any]:
        """
        Local implementation of standee detection.
        """
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
                return {
                    'success': False,
                    'error': 'Failed to decode image bytes'
                }

            try:
                lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
                l, a, b = cv2.split(lab)
                clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
                cl = clahe.apply(l)
                normalized = cv2.merge((cl,a,b))
                img = cv2.cvtColor(normalized, cv2.COLOR_LAB2BGR)
            except Exception as e:
                self.logger.warning(f"Brightness normalization failed: {str(e)}")

            results = model.predict(
                img,
                conf=0.01,   # Absolute minimum confidence for initial detection
                iou=0.10,    # Minimum IoU for maximum recall
                augment=False,
                agnostic_nms=True, # Class-agnostic NMS
                max_det=500,  # Maximum detection limit
                verbose=False
            )

            detections = []
            if len(results) > 0:
                result = results[0]
                if hasattr(result, 'boxes') and hasattr(result, 'masks'):
                    boxes = result.boxes
                    masks = result.masks
                    
                    if hasattr(masks, 'data') and masks.data is not None:
                        masks_data = masks.data.cpu().numpy()
                        
                        for i, (mask, box, cls, conf) in enumerate(zip(
                                masks_data, 
                                boxes.xyxy.cpu().numpy(), 
                                boxes.cls.cpu().numpy(), 
                                boxes.conf.cpu().numpy())):
                            
                            if int(cls) == 0:
                                x1, y1, x2, y2 = box[:4]
                                
                                mask_binary = (mask > 0.5).astype(np.uint8)
                                mask_resized = cv2.resize(
                                    mask_binary,
                                    (img.shape[1], img.shape[0]),
                                    interpolation=cv2.INTER_LINEAR
                                )
                                
                                contours, _ = cv2.findContours(
                                    mask_resized,
                                    cv2.RETR_EXTERNAL,
                                    cv2.CHAIN_APPROX_SIMPLE
                                )
                                
                                if contours:
                                    largest_contour = max(contours, key=cv2.contourArea)
                                    epsilon = 0.005 * cv2.arcLength(largest_contour, True)
                                    polygon = cv2.approxPolyDP(largest_contour, epsilon, True)
                                    
                                    polygon = polygon.astype(np.float32)
                                    polygon[..., 0] = polygon[..., 0] / img.shape[1]
                                    polygon[..., 1] = polygon[..., 1] / img.shape[0]
                                    
                                    bbox_rel = [
                                        float(x1) / img.shape[1],
                                        float(y1) / img.shape[0],
                                        float(x2) / img.shape[1],
                                        float(y2) / img.shape[0]
                                    ]
                                    
                                    detection = {
                                        'confidence': float(conf),
                                        'bbox': bbox_rel,
                                        'segmentation': {
                                            'points': polygon.reshape(-1).tolist(),
                                            'point_count': len(polygon)
                                        },
                                        'box': [float(x1), float(y1), float(x2), float(y2)],
                                        'width': float(x2) - float(x1),
                                        'height': float(y2) - float(y1),
                                        'area': (float(x2) - float(x1)) * (float(y2) - float(y1)),
                                        'aspect_ratio': ((float(x2) - float(x1)) / (float(y2) - float(y1))
                                                        if (float(y2) - float(y1)) > 0 else 0),
                                        'image_height': img.shape[0]
                                    }
                                    
                                    if self._meets_standee_criteria(detection):
                                        detections.append(detection)

            refined_detections = self._enhanced_standee_postprocess(detections)
            
            return {
                'success': True, 
                'detections': refined_detections,
                'count': len(refined_detections)
            }

        except Exception as e:
            return {'success': False, 'error': f'Detection failed: {str(e)}'}

    def _meets_standee_criteria(self, detection: Dict[str, Any]) -> bool:
        """
        Comprehensive implementation of meets_standee_criteria from yolo_bridge.
        Determines if a detection meets the criteria for being a standee.
        """
        if not detection:
            return False
        
        points = np.array(detection['segmentation']['points']).reshape(-1, 2)
        img_height = detection.get('image_height', 1000)
        img_width = img_height * 4/3
        confidence = detection.get('confidence', 0)
        
        points_denorm = points.copy()
        points_denorm[:, 0] *= img_width
        points_denorm[:, 1] *= img_height
        contour = points_denorm.astype(np.float32).reshape(-1, 1, 2)
        
        x_min, y_min = points_denorm.min(axis=0)
        x_max, y_max = points_denorm.max(axis=0)
        width = x_max - x_min
        height = y_max - y_min
        aspect_ratio = height / width if width > 0 else 0
        
        area = cv2.contourArea(contour)
        perimeter = cv2.arcLength(contour, True)
        
        hull = cv2.convexHull(contour)
        hull_area = cv2.contourArea(hull)
        solidity = area / hull_area if hull_area > 0 else 0
        
        rect = cv2.minAreaRect(contour)
        angle = rect[-1]
        box = cv2.boxPoints(rect)
        box_area = cv2.contourArea(np.array([box], dtype=np.float32))
        rect_ratio = area / box_area if box_area > 0 else 0
        
        complexity = perimeter * perimeter / (4 * np.pi * area) if area > 0 else 0
        edges = cv2.Canny(cv2.UMat(contour.astype(np.uint8)), 100, 200)
        edge_ratio = cv2.countNonZero(edges) / contour.shape[0] if contour.shape[0] > 0 else 0
        
        is_partial = (y_min <= 1 or y_max >= img_height - 1 or x_min <= 1 or x_max >= img_width - 1)
        relative_height = height / img_height
        relative_width = width / img_width
        relative_area = area / (img_width * img_height)
        
        if len(points) < (4 if is_partial else 6):
            return False
            
        if not (0.15 <= aspect_ratio <= 6.0 and 0.05 <= relative_height <= 0.95):
            return False
            
        if rect_ratio > 0.93 and solidity > 0.95:
            return False
            
        if (0.75 <= aspect_ratio <= 1.3 and edge_ratio < 0.28 and 
            complexity > 2.2 and solidity < 0.65 and relative_area > 0.15):
            return False
            
        if aspect_ratio < 0.5 and solidity > 0.9 and relative_area < 0.1:
            return False
            
        angle_normalized = abs(angle) % 90
        is_rotated = not (0 <= angle_normalized <= 10 or 80 <= angle_normalized <= 90)
        
        if is_rotated:
            if is_partial:
                return (rect_ratio < 0.97 and complexity >= 1.1 and
                       solidity > 0.20 and relative_area >= 0.01)
            else:
                return (rect_ratio < 0.95 and 1.2 <= complexity <= 8.0 and
                       solidity > 0.30 and 0.02 <= relative_area <= 0.6)
        else:
            if is_partial:
                return (rect_ratio < 0.95 and complexity >= 1.2 and
                       solidity > 0.25 and relative_area >= 0.01 and
                       edge_ratio >= 0.15)
            else:
                standee_valid = (rect_ratio < 0.92 and 1.3 <= complexity <= 7.0 and
                             solidity > 0.35 and 0.02 <= relative_area <= 0.5)
                
                if 0.8 <= aspect_ratio <= 1.4:
                    return standee_valid and edge_ratio >= 0.3 and rect_ratio < 0.9
                return standee_valid
                
        return False

    def _calculate_iou(self, det1: Dict[str, Any], det2: Dict[str, Any]) -> float:
        """Calculate IoU between two detections using their bounding boxes."""
        b1 = det1['bbox']
        b2 = det2['bbox']
        x1 = max(b1[0], b2[0])
        y1 = max(b1[1], b2[1])
        x2 = min(b1[2], b2[2])
        y2 = min(b1[3], b2[3])
        
        if x2 <= x1 or y2 <= y1:
            return 0.0
            
        intersection = (x2 - x1) * (y2 - y1)
        area1 = (b1[2] - b1[0]) * (b1[3] - b1[1])
        area2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
        union = area1 + area2 - intersection
        
        return intersection / union if union > 0 else 0.0
        
    def _enhanced_standee_postprocess(self, detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Post-process detections to remove overlaps and filter by criteria."""
        refined = []
        for i, d in enumerate(detections):
            if not self._meets_standee_criteria(d):
                self.logger.info(f"Detection {i+1} failed criteria check")
                continue
                
            overlaps_with_better = False
            for existing in refined:
                iou = self._calculate_iou(d, existing)
                if iou > 0.5:
                    if existing['confidence'] >= d['confidence']:
                        self.logger.info(f"Detection {i+1} overlaps with higher confidence detection (IoU: {iou:.2f})")
                        overlaps_with_better = True
                        break
                    else:
                        self.logger.info(f"Replacing lower confidence detection with detection {i+1} (IoU: {iou:.2f})")
                        refined.remove(existing)
                        
            if not overlaps_with_better:
                self.logger.info(f"Adding detection {i+1} (confidence: {d['confidence']:.2f})")
                refined.append(d)
                
        self.logger.info(f"Post-processing complete: {len(refined)}/{len(detections)} detections kept")
        return refined
        
    def _get_parameter_metadata(self) -> Dict[str, Dict[str, Any]]:
        """
        Return metadata about tool parameters.

        Returns:
            Dict mapping parameter names to parameter metadata
        """
        return {
            "image_url": {
                "type": "string",
                "description": "URL of the image to analyze for standees",
                "required": True},
            "confidence_threshold": {
                "type": "number",
                "description": "Minimum confidence score (0.0-1.0) for detection",
                "default": 0.25,
                "required": False},
            "image_bytes": {
                "type": "bytes",
                "description": "Raw image bytes to analyze (alternative to image_url)",
                "required": False}}

    def _get_return_metadata(self) -> Dict[str, Any]:
        """
        Return metadata about tool return values.

        Returns:
            Dict describing the return value structure
        """
        return {
            "type": "object",
            "properties": {
                "success": {
                    "type": "boolean",
                    "description": "Whether the detection was successful"
                },
                "detections": {
                    "type": "array",
                    "description": "List of detected standees with details",
                    "items": {
                        "type": "object",
                        "properties": {
                            "box": {
                                "type": "array",
                                "description": "Bounding box coordinates [x1, y1, x2, y2]"
                            },
                            "confidence": {
                                "type": "number",
                                "description": "Confidence score (0.0-1.0)"
                            },
                            "width": {
                                "type": "number",
                                "description": "Width of the detection in pixels"
                            },
                            "height": {
                                "type": "number",
                                "description": "Height of the detection in pixels"
                            },
                            "aspect_ratio": {
                                "type": "number",
                                "description": "Width/height ratio of the detection"
                            }
                        }
                    }
                },
                "count": {
                    "type": "integer",
                    "description": "Number of standees detected"
                },
                "error": {
                    "type": "string",
                    "description": "Error message if detection failed"
                }
            }
        }

    def get_capabilities(self, context: Dict[str, Any]) -> List[str]:
        """
        Return capabilities based on current context.

        Args:
            context: Current execution context

        Returns:
            List of capability strings
        """
        capabilities = [
            "can_detect_standees",
            "can_analyze_images",
            "can_process_image_urls",
            "can_process_image_bytes"
        ]

        if context.get("in_photo_gallery", False):
            capabilities.append("can_analyze_gallery_photos")

        if context.get("in_restaurant_page", False):
            capabilities.append("can_analyze_restaurant_photos")

        return capabilities

    def get_examples(self) -> List[Dict[str, Any]]:
        """
        Return usage examples with inputs and expected outputs.

        Returns:
            List of example dicts
        """
        return [
            {
                "description": "Detect standees in an image from URL",
                "params": {
                    "image_url": "https://example.com/restaurant_photo.jpg",
                    "confidence_threshold": 0.3
                },
                "context": {
                    "in_restaurant_page": True
                },
                "expected_result": {
                    "success": True,
                    "detections": [
                        {
                            "box": [100, 200, 300, 500],
                            "confidence": 0.85,
                            "width": 200,
                            "height": 300,
                            "aspect_ratio": 0.67
                        }
                    ],
                    "count": 1
                }
            },
            {
                "description": "No standees detected in an image",
                "params": {
                    "image_url": "https://example.com/empty_restaurant.jpg"
                },
                "context": {
                    "in_restaurant_page": True
                },
                "expected_result": {
                    "success": True,
                    "detections": [],
                    "count": 0
                }
            }
        ]

    def execute(self, params: Dict[str, Any],
                context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute standee detection with parameters and context.

        Args:
            params: Parameters for tool execution
                - image_url: URL of the image to analyze
                - image_bytes: Raw image bytes to analyze (alternative to image_url)
                - confidence_threshold: Optional confidence threshold
            context: Current execution context

        Returns:
            Dict with execution results
        """
        if "confidence_threshold" in params:
            self.confidence_threshold = params["confidence_threshold"]

        if "image_url" in params:
            result = self.detect_from_url(params["image_url"])
            return self._format_result(result, params, context)

        elif "image_bytes" in params:
            result = self.detect_from_bytes(params["image_bytes"])
            return self._format_result(result, params, context)

        else:
            return self.format_error_result(
                "Missing required parameter: either image_url or image_bytes must be provided",
                metadata={
                    "context": context})

    def _format_result(self,
                       result: Dict[str,
                                    Any],
                       params: Dict[str,
                                    Any],
                       context: Dict[str,
                                     Any]) -> Dict[str,
                                                   Any]:
        """
        Format detection result according to MCP protocol.

        Args:
            result: Raw detection result
            params: Original parameters
            context: Execution context

        Returns:
            Formatted result dict
        """
        if not result.get("success", False):
            return self.format_error_result(
                result.get("error", "Unknown detection error"),
                metadata={
                    "params": params,
                    "context": context
                }
            )

        return self.format_success_result(
            {
                "detections": result.get("detections", []),
                "count": result.get("count", 0)
            },
            metadata={
                "image_source": "url" if "image_url" in params else "bytes",
                "confidence_threshold": self.confidence_threshold,
                "context": context
            }
        )
