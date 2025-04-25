import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from browser_use.tools.standee_detection import (  # noqa: E402
    StandeeDetectionTool
)
from browser_use.tools.registry import ToolRegistry  # noqa: E402


def test_standee_detection_tool_initialization():
    """Test that the standee detection tool initializes properly."""
    tool = StandeeDetectionTool()
    assert tool is not None
    assert tool.confidence_threshold == 0.25
    assert tool.model_path is None


def test_standee_detection_tool_registry():
    """Test that the standee detection tool is properly registered."""
    tool_class = ToolRegistry.get_tool('standee_detection')
    assert tool_class is not None
    assert tool_class == StandeeDetectionTool


@patch('requests.get')
def test_standee_detection_with_sample_image_url(mock_get):
    """Test standee detection with a sample image URL."""
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_response.content = b'sample_image_data'
    mock_get.return_value = mock_response

    with patch.object(
        StandeeDetectionTool, 'detect_from_bytes'
    ) as mock_detect:
        mock_detect.return_value = {
            'success': True,
            'detections': [
                {
                    'box': [100, 200, 300, 400],
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

        tool = StandeeDetectionTool()
        result = tool.detect_from_url('https://example.com/sample_image.jpg')

        assert result['success'] is True
        assert len(result['detections']) == 1
        assert result['count'] == 1
        assert result['detections'][0]['confidence'] == 0.85

        mock_detect.assert_called_once_with(b'sample_image_data')


@patch.object(StandeeDetectionTool, 'load_model')
def test_standee_detection_with_bytes(mock_load_model):
    """Test standee detection with image bytes."""
    mock_model = MagicMock()
    mock_load_model.return_value = mock_model

    with patch('cv2.imdecode') as mock_imdecode, \
         patch('cv2.createCLAHE') as mock_create_clahe, \
         patch('cv2.cvtColor') as mock_cvtcolor, \
         patch('cv2.split') as mock_split, \
         patch('cv2.merge'), \
         patch('numpy.frombuffer') as mock_frombuffer:

        mock_img = MagicMock()
        mock_imdecode.return_value = mock_img
        mock_lab = MagicMock()
        mock_cvtcolor.return_value = mock_lab
        mock_planes = [MagicMock()]
        mock_split.return_value = mock_planes
        mock_clahe = MagicMock()
        mock_create_clahe.return_value = mock_clahe
        mock_frombuffer.return_value = MagicMock()

        mock_result = MagicMock()
        mock_box = MagicMock()
        mock_box.xyxy = [[100, 200, 300, 400]]
        mock_box.conf = [[0.85]]
        mock_box.cls = [[0]]
        mock_result.boxes = [mock_box]
        mock_model.predict.return_value = [mock_result]

        tool = StandeeDetectionTool()
        result = tool._detect_standees_bytes_local(b'sample_image_data')

        assert result['success'] is True
        assert 'detections' in result

        mock_load_model.assert_called_once()


def test_meets_standee_criteria():
    """Test the _meets_standee_criteria method."""
    tool = StandeeDetectionTool(confidence_threshold=0.5)

    detection = {
        'box': [100, 200, 300, 400],
        'confidence': 0.8,
        'width': 200,
        'height': 400,
        'aspect_ratio': 0.5  # Width < Height
    }
    img_shape = (1000, 1000, 3)
    assert tool._meets_standee_criteria(detection, img_shape) is True

    detection['confidence'] = 0.4
    assert tool._meets_standee_criteria(detection, img_shape) is False

    detection['confidence'] = 0.8
    detection['aspect_ratio'] = 1.5
    assert tool._meets_standee_criteria(detection, img_shape) is False

    detection['aspect_ratio'] = 0.5
    detection['width'] = 10  # Less than 5% of image width
    detection['height'] = 20
    assert tool._meets_standee_criteria(detection, img_shape) is False
