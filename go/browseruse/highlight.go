package browseruse

import (
	"bytes"
	"encoding/base64"
	"fmt"
	"image"
	"image/color"
	"image/draw"
	"image/png"
	"math"
	"strconv"
	"strings"

	webpenc "github.com/chai2010/webp"
	"golang.org/x/image/font"
	"golang.org/x/image/font/basicfont"
	"golang.org/x/image/math/fixed"
	_ "golang.org/x/image/webp"
)

type highlightColor struct {
	fill color.RGBA
}

var highlightColors = map[string]highlightColor{
	"button":   {fill: hexToRGBA("#FF6B6B")},
	"input":    {fill: hexToRGBA("#4ECDC4")},
	"select":   {fill: hexToRGBA("#45B7D1")},
	"a":        {fill: hexToRGBA("#96CEB4")},
	"textarea": {fill: hexToRGBA("#FF8C42")},
	"default":  {fill: hexToRGBA("#DDA0DD")},
}

func highlightScreenshot(base64Image string, elements []IndexedElement, devicePixelRatio float64) (string, error) {
	if strings.TrimSpace(base64Image) == "" {
		return base64Image, nil
	}
	decoded, err := base64.StdEncoding.DecodeString(base64Image)
	if err != nil {
		return base64Image, err
	}
	img, _, err := image.Decode(bytes.NewReader(decoded))
	if err != nil {
		return base64Image, err
	}
	bounds := img.Bounds()
	rgba := image.NewRGBA(bounds)
	draw.Draw(rgba, bounds, img, bounds.Min, draw.Src)
	if devicePixelRatio <= 0 {
		devicePixelRatio = 1
	}
	for _, el := range elements {
		bbox := scaleBoundingBox(el.Bounding, devicePixelRatio)
		drawHighlight(rgba, bbox, el, bounds)
	}
	var buffer bytes.Buffer
	if err := webpenc.Encode(&buffer, rgba, &webpenc.Options{Quality: 60}); err != nil {
		buffer.Reset()
		if err := png.Encode(&buffer, rgba); err != nil {
			return base64Image, err
		}
	}
	return base64.StdEncoding.EncodeToString(buffer.Bytes()), nil
}

func drawHighlight(img *image.RGBA, bbox BoundingBox, el IndexedElement, bounds image.Rectangle) {
	x1 := int(math.Round(bbox.X))
	y1 := int(math.Round(bbox.Y))
	x2 := int(math.Round(bbox.X + bbox.Width))
	y2 := int(math.Round(bbox.Y + bbox.Height))

	if x2-x1 < 2 || y2-y1 < 2 {
		return
	}
	if x1 < bounds.Min.X {
		x1 = bounds.Min.X
	}
	if y1 < bounds.Min.Y {
		y1 = bounds.Min.Y
	}
	if x2 > bounds.Max.X {
		x2 = bounds.Max.X
	}
	if y2 > bounds.Max.Y {
		y2 = bounds.Max.Y
	}
	if x2-x1 < 2 || y2-y1 < 2 {
		return
	}

	color := colorForElement(el)
	drawRect(img, x1, y1, x2, y2, color)
	drawLabel(img, x1, y1, color, el.Index)
}

func drawRect(img *image.RGBA, x1, y1, x2, y2 int, c color.RGBA) {
	lineWidth := 2
	for i := 0; i < lineWidth; i++ {
		drawHorizontal(img, x1+i, x2-i, y1+i, c)
		drawHorizontal(img, x1+i, x2-i, y2-1-i, c)
		drawVertical(img, x1+i, y1+i, y2-i, c)
		drawVertical(img, x2-1-i, y1+i, y2-i, c)
	}
}

func drawHorizontal(img *image.RGBA, x1, x2, y int, c color.RGBA) {
	if y < img.Bounds().Min.Y || y >= img.Bounds().Max.Y {
		return
	}
	if x1 > x2 {
		x1, x2 = x2, x1
	}
	if x1 < img.Bounds().Min.X {
		x1 = img.Bounds().Min.X
	}
	if x2 > img.Bounds().Max.X {
		x2 = img.Bounds().Max.X
	}
	for x := x1; x < x2; x++ {
		img.SetRGBA(x, y, c)
	}
}

func drawVertical(img *image.RGBA, x, y1, y2 int, c color.RGBA) {
	if x < img.Bounds().Min.X || x >= img.Bounds().Max.X {
		return
	}
	if y1 > y2 {
		y1, y2 = y2, y1
	}
	if y1 < img.Bounds().Min.Y {
		y1 = img.Bounds().Min.Y
	}
	if y2 > img.Bounds().Max.Y {
		y2 = img.Bounds().Max.Y
	}
	for y := y1; y < y2; y++ {
		img.SetRGBA(x, y, c)
	}
}

func drawLabel(img *image.RGBA, x, y int, c color.RGBA, index int) {
	if index <= 0 {
		return
	}
	label := []byte(fmt.Sprintf("%d", index))
	face := basicfont.Face7x13
	drawer := font.Drawer{Dst: img, Src: image.NewUniform(color.White), Face: face}
	textWidth := drawer.MeasureBytes(label).Ceil()
	textHeight := face.Metrics().Height.Ceil()
	pad := 2
	bgX1 := clampInt(x, img.Bounds().Min.X, img.Bounds().Max.X)
	bgY1 := clampInt(y, img.Bounds().Min.Y, img.Bounds().Max.Y)
	bgX2 := clampInt(x+textWidth+pad*2, img.Bounds().Min.X, img.Bounds().Max.X)
	bgY2 := clampInt(y+textHeight+pad*2, img.Bounds().Min.Y, img.Bounds().Max.Y)
	bg := image.NewUniform(c)
	draw.Draw(img, image.Rect(bgX1, bgY1, bgX2, bgY2), bg, image.Point{}, draw.Src)
	drawer = font.Drawer{Dst: img, Src: image.NewUniform(color.Black), Face: face}
	drawer.Dot = fixed.Point26_6{
		X: fixed.I(bgX1 + pad),
		Y: fixed.I(bgY1 + pad + face.Metrics().Ascent.Ceil()),
	}
	drawer.DrawBytes(label)
}

func scaleBoundingBox(bounding BoundingBox, devicePixelRatio float64) BoundingBox {
	return BoundingBox{
		X:      bounding.X * devicePixelRatio,
		Y:      bounding.Y * devicePixelRatio,
		Width:  bounding.Width * devicePixelRatio,
		Height: bounding.Height * devicePixelRatio,
	}
}

func colorForElement(el IndexedElement) color.RGBA {
	if el.Tag == "input" {
		if typ, ok := el.Attrs["type"]; ok {
			if typ == "button" || typ == "submit" {
				return highlightColors["button"].fill
			}
		}
	}
	if c, ok := highlightColors[el.Tag]; ok {
		return c.fill
	}
	return highlightColors["default"].fill
}

func hexToRGBA(hex string) color.RGBA {
	hex = strings.TrimPrefix(hex, "#")
	if len(hex) != 6 {
		return color.RGBA{R: 255, G: 255, B: 0, A: 255}
	}
	var rgb [3]uint8
	for i := 0; i < 3; i++ {
		part := hex[i*2 : i*2+2]
		value, err := strconv.ParseUint(part, 16, 8)
		if err != nil {
			return color.RGBA{R: 255, G: 255, B: 0, A: 255}
		}
		rgb[i] = uint8(value)
	}
	return color.RGBA{R: rgb[0], G: rgb[1], B: rgb[2], A: 255}
}

func clampInt(value, min, max int) int {
	if value < min {
		return min
	}
	if value > max {
		return max
	}
	return value
}
