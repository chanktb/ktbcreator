import os
import json
import re
import shutil
import zipfile
from datetime import datetime, timedelta
import random
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import piexif
import glob
import requests
from urllib.parse import quote

# --- Cấu hình thư mục ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MOCKUP_DIR = os.path.join(SCRIPT_DIR, "Mockup")
INPUT_DIR = os.path.join(SCRIPT_DIR, "InputImage")
OUTPUT_IMAGE_DIR = os.path.join(SCRIPT_DIR, "OutputImage") 
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
TOTAL_IMAGE_FILE = os.path.join(SCRIPT_DIR, "TotalImage.txt")

# --- Các hàm hỗ trợ ---

def load_total_counts(filepath):
    """Đọc số lượng ảnh đã tạo từ file TotalImage.txt."""
    counts = {}
    if not os.path.exists(filepath):
        print("ℹ️ Không tìm thấy file TotalImage.txt, sẽ tạo file mới sau khi chạy xong.")
        return counts
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                if ':' in line:
                    name, count = line.strip().split(':', 1)
                    counts[name.strip()] = int(count.strip())
        print(f"✅ Đã tải thành công dữ liệu từ: {filepath}")
    except Exception as e:
        print(f"⚠️ Cảnh báo: Không thể đọc file TotalImage.txt. Sẽ bắt đầu đếm lại. Lỗi: {e}")
        return {}
    return counts

def save_total_counts(filepath, counts):
    """Lưu tổng số ảnh vào file TotalImage.txt."""
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            for name, count in sorted(counts.items()):
                f.write(f"{name}: {count}\n")
    except Exception as e:
        print(f"❌ Lỗi khi lưu file TotalImage.txt: {e}")

def cleanup_input_directory(directory, processed_files_list):
    """Xóa các file đã xử lý trong thư mục Input."""
    print(f"\n--- 🗑️ Dọn dẹp thư mục: {directory} ---")
    if not os.path.exists(directory):
        return
    for filename in processed_files_list:
        file_path = os.path.join(directory, filename)
        try:
            if os.path.isfile(file_path):
                os.unlink(file_path)
                print(f"  - Đã xóa: {filename}")
        except Exception as e:
            print(f'Lỗi khi xóa {file_path}. Lý do: {e}')

def _convert_to_gps(value, is_longitude):
    """Chuyển đổi tọa độ thập phân sang định dạng EXIF GPS."""
    abs_value = abs(value)
    ref = ('E' if value >= 0 else 'W') if is_longitude else ('N' if value >= 0 else 'S')
    degrees = int(abs_value)
    minutes_float = (abs_value - degrees) * 60
    minutes = int(minutes_float)
    seconds_float = (minutes_float - minutes) * 60
    return {
        'value': ((degrees, 1), (minutes, 1), (int(seconds_float * 100), 100)),
        'ref': ref.encode('ascii')
    }

def create_exif_data(prefix, final_filename, exif_defaults):
    """Tạo chuỗi bytes EXIF."""
    domain_exif = prefix + ".com"
    digitized_time = datetime.now() - timedelta(hours=2)
    random_seconds = random.randint(3600, 7500)
    original_time = digitized_time - timedelta(seconds=random_seconds)
    digitized_str = digitized_time.strftime("%Y:%m:%d %H:%M:%S")
    original_str = original_time.strftime("%Y:%m:%d %H:%M:%S")
    try:
        zeroth_ifd = {
            piexif.ImageIFD.Artist: domain_exif.encode('utf-8'),
            piexif.ImageIFD.Copyright: domain_exif.encode('utf-8'),
            piexif.ImageIFD.ImageDescription: final_filename.encode('utf-8'),
            piexif.ImageIFD.Software: exif_defaults.get("Software", "Adobe Photoshop 25.0").encode('utf-8'),
            piexif.ImageIFD.DateTime: digitized_str.encode('utf-8'),
            piexif.ImageIFD.Make: exif_defaults.get("Make", "").encode('utf-8'),
            piexif.ImageIFD.Model: exif_defaults.get("Model", "").encode('utf-8'),
            piexif.ImageIFD.XPAuthor: domain_exif.encode('utf-16le'),
            piexif.ImageIFD.XPComment: final_filename.encode('utf-16le'),
            piexif.ImageIFD.XPSubject: final_filename.encode('utf-16le'),
            piexif.ImageIFD.XPKeywords: (prefix + ";" + "shirt;").encode('utf-16le')
        }
        exif_ifd = {
            piexif.ExifIFD.DateTimeOriginal: original_str.encode('utf-8'),
            piexif.ExifIFD.DateTimeDigitized: digitized_str.encode('utf-8'),
            piexif.ExifIFD.FNumber: tuple(exif_defaults.get("FNumber", [0,1])),
            piexif.ExifIFD.ExposureTime: tuple(exif_defaults.get("ExposureTime", [0,1])),
            piexif.ExifIFD.ISOSpeedRatings: exif_defaults.get("ISOSpeedRatings", 0),
            piexif.ExifIFD.FocalLength: tuple(exif_defaults.get("FocalLength", [0,1]))
        }
        gps_ifd = {}
        lat, lon = exif_defaults.get("GPSLatitude"), exif_defaults.get("GPSLongitude")
        if lat is not None and lon is not None:
            gps_lat_data, gps_lon_data = _convert_to_gps(lat, False), _convert_to_gps(lon, True)
            gps_ifd.update({
                piexif.GPSIFD.GPSLatitude: gps_lat_data['value'],
                piexif.GPSIFD.GPSLatitudeRef: gps_lat_data['ref'],
                piexif.GPSIFD.GPSLongitude: gps_lon_data['value'],
                piexif.GPSIFD.GPSLongitudeRef: gps_lon_data['ref']
            })
        return piexif.dump({"0th": zeroth_ifd, "Exif": exif_ifd, "GPS": gps_ifd})
    except Exception as e:
        print(f"Lỗi khi tạo dữ liệu EXIF: {e}")
        return b''

def trim_transparent_background(image):
    """Cắt bỏ toàn bộ phần nền trong suốt thừa xung quanh vật thể."""
    bbox = image.getbbox()
    if bbox:
        return image.crop(bbox)
    return None

def load_config():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Lỗi tải file config: {e}")
        return {}

def download_image_from_url(url):
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
        response.raise_for_status()
        return Image.open(BytesIO(response.content)).convert("RGBA")
    except Exception as e:
        print(f"Lỗi tải watermark từ {url}: {e}")
        return None

def clean_title(title):
    return os.path.splitext(title)[0].replace('-', ' ').replace('_', ' ').strip()

def remove_background(design_img):
    """Xóa nền của ảnh thiết kế bằng logic 'magic wand' từ các góc."""
    design_w, design_h = design_img.size
    pixels, visited = design_img.load(), set()
    
    corner_points = [
        (0, 0), (design_w - 1, 0), (0, design_h - 1), (design_w - 1, design_h - 1),
        (design_w // 2, 0), (design_w // 2, design_h - 1), (0, design_h // 2), (design_w - 1, design_h // 2)
    ]
    
    for start_x, start_y in corner_points:
        if (start_x, start_y) in visited: continue
        
        seed_r, seed_g, seed_b = design_img.getpixel((start_x, start_y))[:3]
        stack = [(start_x, start_y)]
        
        while stack:
            x, y = stack.pop()
            if not (0 <= x < design_w and 0 <= y < design_h) or (x, y) in visited: continue
            
            current_r, current_g, current_b = pixels[x, y][:3]
            
            if all(abs(c1 - c2) < 30 for c1, c2 in zip((current_r, current_g, current_b), (seed_r, seed_g, seed_b))):
                pixels[x, y] = (0, 0, 0, 0)
                visited.add((x, y))
                stack.extend([(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)])
    return design_img

def process_image(design_img, mockup_img, mockup_config, watermark_text):
    # 1. Tách nền và cắt ảnh gọn gàng theo vật thể
    design_with_alpha = remove_background(design_img.copy())
    trimmed_design = trim_transparent_background(design_with_alpha)
    
    # Nếu ảnh trống sau khi tách nền thì bỏ qua
    if not trimmed_design: 
        return None

    # 2. Lấy thông số của khung mockup và đối tượng thiết kế
    coords = mockup_config.get("coords", {})
    mockup_frame_w, mockup_frame_h = coords['w'], coords['h']
    obj_w, obj_h = trimmed_design.size
    
    # 3. Xác định các giá trị padding mong muốn
    padding_x = 20  # Padding trái và phải
    padding_y_top = 20 # Padding trên

    # 4. Tính toán không gian có thể sử dụng cho thiết kế bên trong khung
    available_w = mockup_frame_w - (2 * padding_x)
    available_h = mockup_frame_h - padding_y_top

    # 5. Tính toán tỷ lệ resize (scaling)
    # Ưu tiên resize theo chiều rộng trước
    scale_ratio = available_w / obj_w
    
    # Kiểm tra xem với tỷ lệ này, chiều cao có bị vượt quá khung không
    if (obj_h * scale_ratio) > available_h:
        # Nếu chiều cao vượt quá, ta phải ưu tiên resize theo chiều cao
        scale_ratio = available_h / obj_h

    # 6. Áp dụng tỷ lệ để có kích thước cuối cùng và resize ảnh
    final_w = int(obj_w * scale_ratio)
    final_h = int(obj_h * scale_ratio)
    resized_design = trimmed_design.resize((final_w, final_h), Image.Resampling.LANCZOS)

    # 7. Tính toán tọa độ để dán ảnh vào mockup
    # Tọa độ Y: Căn theo padding top
    paste_y = coords['y'] + padding_y_top
    # Tọa độ X: Căn giữa theo chiều ngang để đảm bảo ảnh luôn cân đối
    paste_x = coords['x'] + (mockup_frame_w - final_w) // 2
    
    # 8. Dán thiết kế đã resize vào ảnh mockup
    final_mockup = mockup_img.copy().convert("RGBA")
    final_mockup.paste(resized_design, (paste_x, paste_y), resized_design)
    
    # Phần xử lý watermark giữ nguyên như cũ
    if watermark_text:
        if watermark_text.startswith(('http', 'https')):
            if watermark_img := download_image_from_url(watermark_text):
                wm_w, wm_h = watermark_img.size
                if wm_w > 280:
                    watermark_img = watermark_img.resize((280, int(280 * wm_h / wm_w)), Image.Resampling.LANCZOS)
                paste_x_wm = final_mockup.width - watermark_img.width - 20
                paste_y_wm = final_mockup.height - watermark_img.height - 50
                final_mockup.paste(watermark_img, (paste_x_wm, paste_y_wm), watermark_img)
        else:
            draw = ImageDraw.Draw(final_mockup)
            font_path = os.path.join(SCRIPT_DIR, "verdanab.ttf")
            font = ImageFont.truetype(font_path, 100) if os.path.exists(font_path) else ImageFont.load_default()
            text_bbox = draw.textbbox((0, 0), watermark_text, font=font)
            text_x = final_mockup.width - (text_bbox[2] - text_bbox[0]) - 20
            text_y = final_mockup.height - (text_bbox[3] - text_bbox[1]) - 50
            draw.text((text_x, text_y), watermark_text, fill=(0, 0, 0, 128), font=font)
            
    return final_mockup.convert("RGB")

def find_mockup_file(mockup_name, color):
    files = glob.glob(os.path.join(MOCKUP_DIR, f"{mockup_name}_{color}.*"))
    return files[0] if files else None

def main():
    print("🚀 Bắt đầu quy trình tạo mockup...")
    
    total_counts = load_total_counts(TOTAL_IMAGE_FILE)

    os.makedirs(OUTPUT_IMAGE_DIR, exist_ok=True)
    for path in [MOCKUP_DIR, INPUT_DIR]:
        os.makedirs(path, exist_ok=True)

    configs = load_config()
    if not configs:
        print("❌ Dừng lại do không thể tải file config.")
        return
        
    defaults, mockup_sets = configs.get("defaults", {}), configs.get("mockup_sets", {})
    output_format, exif_defaults = defaults.get("global_output_format", "webp"), defaults.get("exif_defaults", {})
    
    images_to_process = [f for f in os.listdir(INPUT_DIR) if os.path.isfile(os.path.join(INPUT_DIR, f)) and not f.startswith('.')]

    if not images_to_process:
        print("✅ Không có ảnh mới để xử lý.")
        return

    print(f"🔎 Tìm thấy {len(images_to_process)} ảnh mới để xử lý.")
    images_for_output = {}
    total_generated_count = 0
    run_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    for image_filename in images_to_process:
        print(f"\n--- 🖼️ Đang xử lý: {image_filename} ---")
        try:
            with Image.open(os.path.join(INPUT_DIR, image_filename)) as img:
                img = img.convert("RGBA")
                is_background_light = sum(img.getpixel((5, 5))[:3]) / 3 > 128
                for mockup_name, mockup_config in mockup_sets.items():
                    if mockup_config.get("action", "generate").lower() == "skip":
                        print(f"  - ⏩ Bỏ qua mockup: '{mockup_name}'.")
                        continue

                    if mockup_file_path := find_mockup_file(mockup_name, "white" if is_background_light else "black"):
                        print(f"  - Áp dụng mockup: '{mockup_name}' ({'white' if is_background_light else 'black'})")
                        with Image.open(mockup_file_path) as mockup_img:
                            if final_mockup := process_image(img, mockup_img, mockup_config, mockup_config.get("watermark_text")):
                                prefix, suffix = mockup_config.get("title_prefix_to_add", ""), mockup_config.get("title_suffix_to_add", "")
                                final_filename = f"{prefix} {clean_title(image_filename)} {suffix}".strip().replace('  ', ' ') + f".{output_format}"
                                exif_bytes = create_exif_data(mockup_name, final_filename, exif_defaults)
                                img_byte_arr = BytesIO()
                                final_mockup.save(img_byte_arr, format="WEBP" if output_format == "webp" else "JPEG", quality=90, exif=exif_bytes)
                                
                                if mockup_name not in images_for_output:
                                    images_for_output[mockup_name] = []
                                images_for_output[mockup_name].append((final_filename, img_byte_arr.getvalue()))
                                total_generated_count += 1
                
                print(f"  - ✅ Đã xử lý xong ảnh: {image_filename}")
        except Exception as e:
            print(f"❌ Lỗi nghiêm trọng khi xử lý file {image_filename}: {e}")

    if images_for_output:
        print("\n--- 💾 Bắt đầu lưu ảnh vào các thư mục ---")
        for mockup_name, image_list in images_for_output.items():
            images_in_current_run = len(image_list)
            
            previous_total = total_counts.get(mockup_name, 0)
            total_counts[mockup_name] = previous_total + images_in_current_run
            
            output_subdir_name = f"{mockup_name}.{run_timestamp}.{images_in_current_run}"
            output_path = os.path.join(OUTPUT_IMAGE_DIR, output_subdir_name)
            os.makedirs(output_path, exist_ok=True)
            
            print(f"  - Đang tạo và lưu {images_in_current_run} ảnh vào: {output_path}")
            for filename, data in image_list:
                file_path = os.path.join(output_path, filename)
                with open(file_path, 'wb') as f:
                    f.write(data)

    if images_to_process:
        cleanup_input_directory(INPUT_DIR, images_to_process)

    if total_counts:
        save_total_counts(TOTAL_IMAGE_FILE, total_counts)
        print(f"✅ Đã cập nhật tổng số ảnh trong file: {os.path.basename(TOTAL_IMAGE_FILE)}")


    print(f"\n--- ✨ Hoàn tất! ---")
    print(f"Tổng số ảnh đã xử lý trong lần chạy này: {len(images_to_process)}")
    print(f"Tổng số mockup đã tạo trong lần chạy này: {total_generated_count}")
    print(f"Kết quả được lưu tại thư mục: {OUTPUT_IMAGE_DIR}")

if __name__ == "__main__":
    main()