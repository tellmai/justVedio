from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1]
image = Image.new('RGBA', (512,512), (0,0,0,0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((24,24,488,488), radius=110, fill='#2464ac')
draw.rounded_rectangle((85,105,427,360), radius=28, outline='#d9efff', width=18)
draw.polygon([(215,163),(215,304),(335,233)], fill='#71e2b4')
draw.line((190,411,322,411), fill='#d9efff', width=18)
draw.line((256,367,256,408), fill='#d9efff', width=18)
destination = root / 'justvedio/assets/app.ico'
destination.parent.mkdir(parents=True, exist_ok=True)
image.save(destination, sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
print(destination)
