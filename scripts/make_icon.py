from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1]
image = Image.new('RGBA', (512,512), (0,0,0,0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((24,24,488,488), radius=135, fill='#137e74')
draw.polygon([(194,148),(194,364),(364,256)], fill='#ffffff')
destination = root / 'justvedio/assets/app.ico'
destination.parent.mkdir(parents=True, exist_ok=True)
image.save(destination, sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
print(destination)
