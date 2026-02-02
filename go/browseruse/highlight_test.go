package browseruse

import (
	"bytes"
	"encoding/base64"
	"image"
	"image/color"
	"image/draw"
	"image/png"
	"testing"

	_ "golang.org/x/image/webp"
)

func TestHighlightScreenshotDrawsBox(t *testing.T) {
	img := image.NewRGBA(image.Rect(0, 0, 50, 50))
	draw.Draw(img, img.Bounds(), &image.Uniform{C: color.RGBA{R: 255, G: 255, B: 255, A: 255}}, image.Point{}, draw.Src)
	var buffer bytes.Buffer
	if err := png.Encode(&buffer, img); err != nil {
		t.Fatalf("encode png: %v", err)
	}
	base64PNG := base64.StdEncoding.EncodeToString(buffer.Bytes())
	elements := []IndexedElement{
		{
			Index:    1,
			Tag:      "button",
			Attrs:    map[string]string{"type": "button"},
			Bounding: BoundingBox{X: 5, Y: 5, Width: 10, Height: 10},
		},
	}

	result, err := highlightScreenshot(base64PNG, elements, 1)
	if err != nil {
		t.Fatalf("highlightScreenshot error: %v", err)
	}
	decoded, err := base64.StdEncoding.DecodeString(result)
	if err != nil {
		t.Fatalf("decode result: %v", err)
	}
	output, _, err := image.Decode(bytes.NewReader(decoded))
	if err != nil {
		t.Fatalf("decode image: %v", err)
	}
	pixel := output.At(5, 5)
	if rgba, ok := pixel.(color.RGBA); ok {
		if rgba.R == 255 && rgba.G == 255 && rgba.B == 255 {
			t.Fatalf("expected highlighted pixel, got white")
		}
	} else {
		r, g, b, _ := pixel.RGBA()
		if r == 0xffff && g == 0xffff && b == 0xffff {
			t.Fatalf("expected highlighted pixel, got white")
		}
	}
}
