import os
from PIL import Image, ImageDraw, ImageFilter
import numpy as np

def create_bottom_right_rainbow_icon(source_path, out_png, out_ico, size=1024):
    img = Image.open(source_path).convert("RGBA")
    img = img.resize((size, size), Image.Resampling.LANCZOS)
    
    # Create overlay for the mini rainbow gradient beam in the bottom right corner
    overlay = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    
    # Colors: Violet, Royal Blue, Cyan, Green, Yellow, Orange, Red, Magenta
    rainbow_colors = [
        (148, 0, 211, 230),   # Violet
        (75, 0, 130, 230),    # Indigo
        (0, 120, 255, 230),   # Blue
        (0, 230, 255, 230),   # Cyan
        (0, 255, 120, 230),   # Green
        (255, 235, 0, 230),   # Yellow
        (255, 130, 0, 230),   # Orange
        (255, 20, 80, 230),   # Red
        (255, 80, 220, 230),  # Pink/Magenta
    ]
    
    # Origin of the beam near bottom-right corner point
    origin_x = size * 0.95
    origin_y = size * 0.95
    
    num_lines = len(rainbow_colors)
    ray_length = size * 0.26  # Mini, tucked into bottom-right
    
    for i, col in enumerate(rainbow_colors):
        angle_deg = 180 + (i / (num_lines - 1)) * 90  # 180 (left) to 270 (up)
        angle_rad = np.radians(angle_deg)
        
        end_x = origin_x + ray_length * np.cos(angle_rad)
        end_y = origin_y + ray_length * np.sin(angle_rad)
        
        line_w = int(size * 0.015)
        draw.line([(origin_x, origin_y), (end_x, end_y)], fill=col, width=line_w)
    
    # Soft luminous bloom
    glow = overlay.filter(ImageFilter.GaussianBlur(radius=size * 0.01))
    
    # Sharp core lines
    sharp_overlay = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    sharp_draw = ImageDraw.Draw(sharp_overlay)
    for i, col in enumerate(rainbow_colors):
        angle_deg = 180 + (i / (num_lines - 1)) * 90
        angle_rad = np.radians(angle_deg)
        end_x = origin_x + (ray_length * 0.96) * np.cos(angle_rad)
        end_y = origin_y + (ray_length * 0.96) * np.sin(angle_rad)
        sharp_col = (col[0], col[1], col[2], 255)
        sharp_draw.line([(origin_x, origin_y), (end_x, end_y)], fill=sharp_col, width=int(size * 0.007))
        
    # Origin spark
    sharp_draw.ellipse(
        [origin_x - size*0.018, origin_y - size*0.018, origin_x + size*0.018, origin_y + size*0.018],
        fill=(255, 255, 255, 255)
    )

    final_img = Image.alpha_composite(img, glow)
    final_img = Image.alpha_composite(final_img, sharp_overlay)
    
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    final_img.save(out_png, "PNG")
    
    # Multi-resolution ICO (256, 128, 64, 48, 32, 16)
    ico_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    final_img.save(out_ico, format="ICO", sizes=ico_sizes)
    print(f"Generated {out_png} and {out_ico}")

def convert_ai_icon(source_path, out_png, out_ico, size=1024):
    img = Image.open(source_path).convert("RGBA")
    img = img.resize((size, size), Image.Resampling.LANCZOS)
    img.save(out_png, "PNG")
    ico_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    img.save(out_ico, format="ICO", sizes=ico_sizes)
    print(f"Generated {out_png} and {out_ico}")

if __name__ == "__main__":
    src_qr = "/home/henry/.gemini/antigravity/brain/30e7d299-434e-4b52-8e68-be03941a5dab/.user_uploaded/media_1786735381397.png"
    src_ai = "/home/henry/.gemini/antigravity/brain/30e7d299-434e-4b52-8e68-be03941a5dab/chromabeam_app_icon_1786735529097.jpg"
    
    assets_dir = "/home/henry/Documents/Projects/Python/QR ChromaBeam/assets"
    web_dir = "/home/henry/Documents/Projects/Python/QR ChromaBeam/web"
    brain_dir = "/home/henry/.gemini/antigravity/brain/30e7d299-434e-4b52-8e68-be03941a5dab"
    
    create_bottom_right_rainbow_icon(src_qr, f"{assets_dir}/icon.png", f"{assets_dir}/icon.ico")
    create_bottom_right_rainbow_icon(src_qr, f"{brain_dir}/icon_rainbow.png", f"{brain_dir}/icon_rainbow.ico")
    create_bottom_right_rainbow_icon(src_qr, f"{web_dir}/favicon.png", f"{web_dir}/favicon.ico")
    
    convert_ai_icon(src_ai, f"{assets_dir}/icon_stylized.png", f"{assets_dir}/icon_stylized.ico")
    convert_ai_icon(src_ai, f"{brain_dir}/icon_stylized.png", f"{brain_dir}/icon_stylized.ico")
