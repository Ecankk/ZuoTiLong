"""Local, validated handwritten-answer images; no arbitrary path inputs."""
from io import BytesIO
import hashlib
from pathlib import Path
import uuid

MAX_IMAGES = 4
MAX_BYTES = 8 * 1024 * 1024


def init_answer_images(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS answer_images(
      id TEXT PRIMARY KEY, path TEXT NOT NULL, source_sha256 TEXT NOT NULL UNIQUE,
      sha256 TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL)""")


def image_records(conn, ids):
    if ids is None:
        ids = []
    if not isinstance(ids, list) or len(ids) > MAX_IMAGES or any(not isinstance(i, str) or len(i) != 38 or not i.startswith('image-') for i in ids):
        raise ValueError("每次最多上传 4 张作答照片，请重新选择图片")
    if len(set(ids)) != len(ids):
        raise ValueError("请勿重复附加相同图片")
    result = []
    for image_id in ids:
        row = conn.execute("SELECT * FROM answer_images WHERE id=?", (image_id,)).fetchone()
        if not row:
            raise ValueError("作答图片不存在，请重新上传")
        result.append(dict(row))
    return result


def public_image(record):
    return {"id": record['id'], "url": f"/api/answer-images/{record['id']}", "width":record['width'], "height":record['height']}


def image_path(record, data_root):
    path = (data_root / record['path']).resolve()
    if not path.is_relative_to((data_root / 'answer-images').resolve()) or not path.is_file():
        raise ValueError("作答图片文件缺失或位置不合法")
    if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
        raise ValueError("作答图片内容已改变，请重新上传")
    return path


def save_answer_image(conn, data_root: Path, content: bytes):
    if not content or len(content) > MAX_BYTES:
        raise ValueError("每张作答图片须小于 8 MB")
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        with Image.open(BytesIO(content)) as source:
            if source.format not in ('JPEG', 'PNG', 'WEBP'):
                raise ValueError("请使用 JPG、PNG 或 WebP 照片（HEIC 请先转换）")
            if getattr(source, 'n_frames', 1) != 1 or source.width * source.height > 32_000_000:
                raise ValueError("请上传单张静态照片，像素不超过 3200 万")
            source.load()
            image = ImageOps.exif_transpose(source).convert('RGBA')
            canvas = Image.new('RGB', image.size, 'white')
            canvas.paste(image, mask=image.getchannel('A'))
            normalized = BytesIO()
            canvas.save(normalized, format='JPEG', quality=95)
            width, height = canvas.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("图片无法读取，请重新拍照或选择 JPG、PNG、WebP 文件") from exc
    digest = hashlib.sha256(content).hexdigest()
    previous = conn.execute("SELECT * FROM answer_images WHERE source_sha256=?", (digest,)).fetchone()
    if previous:
        image_path(previous, data_root)
        return public_image(previous)
    image_id = 'image-' + uuid.uuid4().hex
    folder = data_root / 'answer-images' / image_id
    folder.mkdir(parents=True, exist_ok=False)
    raw = normalized.getvalue()
    # Preserve the original locally; send the orientation-corrected, metadata-free image.
    (folder / 'original').write_bytes(content)
    target = folder / 'answer.jpg'
    target.write_bytes(raw)
    conn.execute("INSERT INTO answer_images VALUES(?,?,?,?,?,?)", (image_id,str(target.relative_to(data_root)),digest,hashlib.sha256(raw).hexdigest(),width,height))
    return {"id":image_id,"url":f"/api/answer-images/{image_id}","width":width,"height":height}
