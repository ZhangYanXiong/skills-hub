"""测试本地媒体预览的HTTP字节区间，避免播放器能播却不能拖动。"""
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_core import SCRIPTS
if (SCRIPTS / 'preview.py').exists():
    import preview
else:
    preview = None


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(preview, '支持字节区间的媒体预览尚未实现')
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'video.mp4').write_bytes(b'0123456789')
        (self.root / 'empty.mp4').write_bytes(b'')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(preview.MediaHandler, directory=str(self.root)))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.close_server)
        self.origin = f'http://127.0.0.1:{self.server.server_port}'

    def close_server(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)

    def request(self, range_header=None, method='GET', path='/video.mp4'):
        headers = {} if range_header is None else {'Range': range_header}
        return urlopen(Request(self.origin + path, headers=headers, method=method), timeout=3)

    def test_full_file_advertises_ranges(self):
        with self.request() as result:
            self.assertEqual(result.status, 200)
            self.assertEqual(result.headers['Accept-Ranges'], 'bytes')
            self.assertEqual(result.read(), b'0123456789')

    def test_partial_range_returns_exact_bytes(self):
        with self.request('bytes=2-5') as result:
            self.assertEqual(result.status, 206)
            self.assertEqual(result.headers['Content-Range'], 'bytes 2-5/10')
            self.assertEqual(result.headers['Content-Length'], '4')
            self.assertEqual(result.read(), b'2345')

    def test_open_ended_and_suffix_ranges(self):
        for range_header, expected in [('bytes=7-', b'789'), ('bytes=-3', b'789'), ('bytes=8-99', b'89')]:
            with self.subTest(range_header=range_header), self.request(range_header) as result:
                self.assertEqual(result.status, 206)
                self.assertEqual(result.read(), expected)

    def test_bad_ranges_fail_without_returning_whole_file(self):
        for header in ['bytes=99-', 'bytes=7-2', 'bytes=-0', 'bytes=0-1,3-5', 'garbage']:
            with self.subTest(header=header), self.assertRaises(HTTPError) as error:
                self.request(header)
            self.assertEqual(error.exception.code, 416)
            self.assertEqual(error.exception.headers['Content-Range'], 'bytes */10')

    def test_head_range_has_headers_but_no_body(self):
        with self.request('bytes=2-5', method='HEAD') as result:
            self.assertEqual(result.status, 206)
            self.assertEqual(result.read(), b'')
            self.assertEqual(result.headers['Content-Length'], '4')

    def test_empty_file_rejects_range(self):
        with self.assertRaises(HTTPError) as error:
            self.request('bytes=0-', path='/empty.mp4')
        self.assertEqual(error.exception.code, 416)

    def test_external_symlink_not_served(self):
        (self.root / 'escape').symlink_to(Path(__file__).resolve())
        with self.assertRaises(HTTPError) as error:
            self.request(path='/escape')
        self.assertEqual(error.exception.code, 403)

    def test_directory_index_external_symlink_not_served(self):
        (self.root / 'chapter').mkdir()
        for directory in [self.root, self.root / 'chapter']:
            (directory / 'index.html').symlink_to(Path(__file__).resolve())
        for path in ['/', '/chapter/']:
            with self.subTest(path=path):
                with self.assertRaises(HTTPError) as error:
                    self.request(path=path)
                self.assertEqual(error.exception.code, 403)

    def test_directory_index_supports_same_range_policy(self):
        (self.root / 'index.html').write_bytes(b'0123456789')
        with self.request('bytes=2-5', path='/') as result:
            self.assertEqual(result.status, 206)
            self.assertEqual(result.read(), b'2345')


if __name__ == '__main__':
    unittest.main()
