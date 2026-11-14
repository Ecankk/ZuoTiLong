import hashlib,json,tempfile,unittest,zipfile
from pathlib import Path
from scripts.packaging.lock_wheels import record


class PackagingLockTests(unittest.TestCase):
    def test_root_metadata_and_wheel_hash_survive_vendor_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);wheels=root/'wheels';wheels.mkdir();wheel=wheels/'sample-1.0-py3-none-any.whl'
            with zipfile.ZipFile(wheel,'w') as archive:
                archive.writestr('sample-1.0.dist-info/METADATA','Name: Sample\nVersion: 1.0\n')
                archive.writestr('sample/vendor/other-9.dist-info/METADATA','Name: Other\nVersion: 9\n')
            result=record(wheels,root/'output');self.assertEqual(len(result),1)
            self.assertEqual(result[0]['name'],'sample');self.assertEqual(result[0]['sha256'],hashlib.sha256(wheel.read_bytes()).hexdigest())
            self.assertIn('sample==1.0 --hash=sha256:',(root/'output/requirements-win-x64-py312.lock').read_text())
