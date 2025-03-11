"""
FastAPI server for OmniParser integration.
"""

import base64
import io
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import torch
from PIL import Image

from util.utils import (
    check_ocr_box,
    get_yolo_model,
    get_caption_model_processor,
    get_som_labeled_img
)

app = FastAPI(title="OmniParser Local Server")

# Initialize models
yolo_model = get_yolo_model(model_path='weights/icon_detect/model.pt')
caption_model_processor = get_caption_model_processor(
    model_name="florence2",
    model_name_or_path="weights/icon_caption_florence"
)

class ImageRequest(BaseModel):
    image_url: str  # Base64 encoded image
    box_threshold: float = 0.05
    iou_threshold: float = 0.1
    use_paddleocr: bool = True
    imgsz: int = 640

class Element(BaseModel):
    type: str
    content: str
    bbox_px: list
    is_interactive: bool

class ParseResponse(BaseModel):
    elements: list[Element]

@app.post("/screen/parse", response_model=ParseResponse)
async def parse_screen(request: ImageRequest):
    try:
        # Extract base64 data
        if request.image_url.startswith('data:image/'):
            image_data = request.image_url.split(',')[1]
        else:
            image_data = request.image_url
            
        # Save image temporarily
        image_data = base64.b64decode(image_data)
        image = Image.open(io.BytesIO(image_data))
        temp_path = 'temp_image.png'
        image.save(temp_path)
        
        # Process with OmniParser
        ocr_bbox_rslt, _ = check_ocr_box(
            temp_path,
            display_img=False,
            output_bb_format='xyxy',
            goal_filtering=None,
            easyocr_args={'paragraph': False, 'text_threshold': 0.9},
            use_paddleocr=request.use_paddleocr
        )
        text, ocr_bbox = ocr_bbox_rslt
        
        # Get labeled elements
        _, label_coordinates, parsed_content_list = get_som_labeled_img(
            temp_path,
            yolo_model,
            BOX_TRESHOLD=request.box_threshold,
            output_coord_in_ratio=True,
            ocr_bbox=ocr_bbox,
            caption_model_processor=caption_model_processor,
            ocr_text=text,
            iou_threshold=request.iou_threshold,
            imgsz=request.imgsz
        )
        
        # Convert to API response format
        elements = []
        for i, content in enumerate(parsed_content_list):
            coords = label_coordinates[i]
            elements.append(Element(
                type="icon" if "icon" in content else "text",
                content=content,
                bbox_px=[
                    coords[0] * image.width,
                    coords[1] * image.height,
                    coords[2] * image.width,
                    coords[3] * image.height
                ],
                is_interactive=True  # You may want to add logic to determine this
            ))
        
        return ParseResponse(elements=elements)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 