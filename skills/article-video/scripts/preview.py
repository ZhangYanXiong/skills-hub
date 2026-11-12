#!/usr/bin/env python3
"""仅本机可访问的媒体预览，支持浏览器拖动所需的 HTTP Range。"""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from urllib.parse import urlsplit


class MediaHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        # 不逐条记录文章文件路径；HTTP状态由浏览器network工具核验。
        pass

    def send_head(self):
        path = Path(self.translate_path(self.path)).resolve()
        root = Path(self.directory).resolve()
        self.byte_range = None
        if not path.is_relative_to(root):
            self.send_error(403, explain='不允许访问预览目录外的文件')
            return None
        if path.is_dir():
            # 目录首页必须经过同一资源边界检查，不能让基类跟随外部 index 符号链接。
            for index in ['index.html', 'index.htm']:
                candidate = (path / index).resolve()
                if not candidate.is_relative_to(root):
                    self.send_error(403, explain='不允许访问预览目录外的文件')
                    return None
                if candidate.is_file():
                    if not urlsplit(self.path).path.endswith('/'):
                        return super().send_head()  # 保留标准的目录尾斜杠重定向。
                    path = candidate
                    break
            else:
                return super().send_head()
        try:
            stream = path.open('rb')
        except OSError:
            self.send_error(404, explain='文件不存在')
            return None
        size = path.stat().st_size
        header = self.headers.get('Range')
        start, end = 0, size - 1
        if header:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', header.strip())
            valid = match is not None and size > 0 and bool(match[1] or match[2])
            if valid:
                if match[1]:
                    start = int(match[1]); end = min(int(match[2]), size - 1) if match[2] else size - 1
                else:
                    suffix = int(match[2]); start = max(0, size - suffix)
                    valid = suffix > 0
                valid = valid and 0 <= start <= end < size
            if not valid:
                stream.close()
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return None
            self.byte_range = (start, end)
        self.send_response(206 if self.byte_range else 200)
        self.send_header('Content-Type', self.guess_type(str(path)))
        self.send_header('Content-Length', str(end - start + 1 if size else 0))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Cache-Control', 'no-store')
        if self.byte_range:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        stream.seek(start)
        return stream

    def copyfile(self, source, outputfile):
        if self.byte_range is None:
            return super().copyfile(source, outputfile)
        remaining = self.byte_range[1] - self.byte_range[0] + 1
        while remaining:
            block = source.read(min(65536, remaining))
            if not block:
                break
            outputfile.write(block)
            remaining -= len(block)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8092)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if not directory.is_dir() or not 1 <= args.port <= 65535:
        parser.error('预览目录必须存在，端口必须在1–65535之间')
    handler = partial(MediaHandler, directory=str(directory))
    with ThreadingHTTPServer(('127.0.0.1', args.port), handler) as server:
        print(f'本地视频预览：http://127.0.0.1:{args.port}', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
