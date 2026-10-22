from contextlib import closing
from io import BytesIO
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PIL import Image
from answer_images import init_answer_images, save_answer_image, image_records, image_path


class AnswerImageTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'tmp').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tmp',prefix='answer-image-test-')
        self.data=Path(self.temp.name)
        self.conn=sqlite3.connect(':memory:');self.conn.row_factory=sqlite3.Row
        init_answer_images(self.conn)

    def tearDown(self):
        self.conn.close();self.temp.cleanup()

    def content(self):
        raw=BytesIO();image=Image.new('RGB',(80,40),'white')
        exif=Image.Exif();exif[274]=6;exif[306]='2026:10:23 12:00:00'
        image.save(raw,format='JPEG',exif=exif)
        return raw.getvalue()

    def test_orientation_metadata_original_and_deduplication(self):
        raw=self.content();asset=save_answer_image(self.conn,self.data,raw)
        record=image_records(self.conn,[asset['id']])[0]
        with Image.open(image_path(record,self.data)) as image:
            self.assertEqual(image.size,(40,80));self.assertEqual(len(image.getexif()),0)
        self.assertEqual((self.data/record['path']).parent.joinpath('original').read_bytes(),raw)
        self.assertEqual(save_answer_image(self.conn,self.data,raw)['id'],asset['id'])
        self.assertNotIn('path',asset)

    def test_invalid_bytes_limits_and_untrusted_ids(self):
        for raw in (b'',b'not an image',b'x'*(8*1024*1024+1)):
            with self.assertRaises(ValueError):save_answer_image(self.conn,self.data,raw)
        for ids in ('file:///private',['../private'],['image-'+'0'*32]*5):
            with self.assertRaises(ValueError):image_records(self.conn,ids)

    def test_changed_image_and_path_escape_are_not_read(self):
        asset=save_answer_image(self.conn,self.data,self.content())
        record=image_records(self.conn,[asset['id']])[0]
        with self.assertRaises(ValueError):image_path({**record,'path':'../outside.jpg'},self.data)
        image_path(record,self.data).write_bytes(b'changed')
        with self.assertRaises(ValueError):image_path(record,self.data)


if __name__=='__main__':unittest.main()
